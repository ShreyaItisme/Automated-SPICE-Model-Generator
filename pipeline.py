import sqlite3
import re
import math
import os

# --- Stage 0: Database Initialization ---

def init_db(db_path="spice_parse.db"):
    """Creates the normalized tables with relational foreign keys."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS components (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            part_number TEXT UNIQUE NOT NULL,
            manufacturer TEXT,
            package TEXT
        )
    """)
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS electrical_specs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            component_id INTEGER UNIQUE,
            gbw_hz REAL NOT NULL,
            avol_linear REAL NOT NULL,
            slew_rate_v_s REAL,
            rin_ohm REAL DEFAULT 1e7,
            rout_ohm REAL DEFAULT 50.0,
            FOREIGN KEY (component_id) REFERENCES components (id) ON DELETE CASCADE
        )
    """)
    conn.commit()
    conn.close()

# --- Stage 1: Parsing & Unit Scaling ---

SI_FACTORS = {
    'p': 1e-12, 'n': 1e-9, 'u': 1e-6, 'µ': 1e-6, 'm': 1e-3,
    'k': 1e3,   'K': 1e3,  'meg': 1e6, 'M': 1e6,  'G': 1e9
}

def extract_metric(text: str, pattern: str) -> float:
    """Extracts a numeric quantity with engineering units and scales to base SI."""
    # Matches the metric, allows optional descriptor words (e.g. 'Product'),
    # followed by optional ':' or '=', then the numeric value and unit prefix.
    regex = rf"{pattern}[^0-9\n\r:]*[:=]?\s*([0-9]*\.?[0-9]+)\s*([a-zA-Zµ]*)"
    match = re.search(regex, text, re.IGNORECASE)
    if not match:
        raise ValueError(f"Pattern '{pattern}' not matched.")
        
    num_str, unit_str = match.groups()
    val = float(num_str)
    
    # Scale engineering prefixes to base SI
    for prefix, factor in sorted(SI_FACTORS.items(), key=lambda x: -len(x[0])):
        if unit_str.startswith(prefix):
            return val * factor
    return val

def parse_datasheet_snippet(raw_text: str) -> dict:
    """Parses raw text into standard normalized metrics."""
    # 1. Gain Bandwidth Product
    gbw = extract_metric(raw_text, r"(?:GBW|Gain Bandwidth|Bandwidth)")
    
    # 2. Open Loop Gain (Linear or dB)
    avol_val = extract_metric(raw_text, r"(?:Avol|Open Loop Gain|Voltage Gain)")
    # If open-loop gain is documented in dB (typically 60dB - 140dB), convert to linear ratio
    if "db" in raw_text.lower():
        avol_linear = 10.0 ** (avol_val / 20.0)
    else:
        avol_linear = avol_val

    # 3. Optional Slew Rate
    try:
        slew_rate = extract_metric(raw_text, r"(?:Slew Rate|SR)")
    except ValueError:
        slew_rate = 1e6  # 1 V/us default

    return {
        "gbw": gbw,
        "avol": avol_linear,
        "slew_rate": slew_rate
    }

# --- Stage 2: Database Storage (ACID Transaction) ---

def save_to_db(db_path: str, part_number: str, specs: dict, manufacturer="Generic", package="SOIC-8"):
    """Inserts metadata and parameters atomically into the relational database."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    try:
        # Atomic transaction begins automatically in sqlite3
        cur.execute("""
            INSERT OR REPLACE INTO components (part_number, manufacturer, package)
            VALUES (?, ?, ?)
        """, (part_number, manufacturer, package))
        
        cur.execute("SELECT id FROM components WHERE part_number = ?", (part_number,))
        comp_id = cur.fetchone()[0]

        cur.execute("""
            INSERT OR REPLACE INTO electrical_specs 
            (component_id, gbw_hz, avol_linear, slew_rate_v_s, rin_ohm, rout_ohm)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (comp_id, specs['gbw'], specs['avol'], specs['slew_rate'], 1e7, 50.0))

        conn.commit()  # Commit transaction
        print(f"Successfully committed '{part_number}' to database.")
    except Exception as e:
        conn.rollback()  # Rollback on error
        raise e
    finally:
        conn.close()

# --- Stage 3: Circuit Modeling & Netlist Synthesis ---

def generate_subcircuit_from_db(db_path: str, part_number: str, output_file: str):
    """Queries specs from DB, computes small-signal elements, and generates .SUBCKT."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    cur.execute("""
        SELECT s.gbw_hz, s.avol_linear, s.rin_ohm, s.rout_ohm
        FROM electrical_specs s
        JOIN components c ON s.component_id = c.id
        WHERE c.part_number = ?
    """, (part_number,))
    row = cur.fetchone()
    conn.close()

    if not row:
        raise ValueError(f"No specifications found for part: {part_number}")

    gbw, avol, rin, rout = row

    # Small-signal derivation math:
    # GBW = gm / (2 * pi * Cc)  =>  gm = 2 * pi * GBW * Cc
    c_comp = 30e-12                          # Standard 30 pF internal compensation
    gm = 2.0 * math.pi * gbw * c_comp        # Required transconductance
    r_dom = avol / gm                        # Dominant resistance sets DC gain (Avol = gm * Rdom)

    subcircuit_content = f"""* Programmatically Generated SPICE Model
* Source Part: {part_number}
.SUBCKT {part_number} IN_P IN_M VCC VEE OUT

* Input Stage: Differential input impedance
R_IN IN_P IN_M {rin:.4e}

* Gain & Dominant Pole Stage:
* Voltage-Controlled Current Source (VCCS) driving parallel R-C tank
G_GAIN 0 N_DOM IN_P IN_M {gm:.6e}
R_DOM  N_DOM 0 {r_dom:.4e}
C_DOM  N_DOM 0 {c_comp:.4e}

* Output Stage: Unity-gain buffer isolating dominant pole from load
E_BUF OUT_INT 0 N_DOM 0 1.0
R_OUT OUT_INT OUT {rout:.2f}

.ENDS {part_number}
"""
    with open(output_file, "w") as f:
        f.write(subcircuit_content)

    print(f"SPICE model written to: {output_file}")

# --- Execution Flow ---

if __name__ == "__main__":
    db_file = "spice_parse.db"
    init_db(db_file)

    # 1. Sample raw datasheet string input
    datasheet_sample = """
    Operational Amplifier Model: OPA820
    Gain Bandwidth Product: 280 MHz
    Open Loop Gain: 74 dB
    Slew Rate: 240 V/us
    """

    # 2. Parse text
    parsed_specs = parse_datasheet_snippet(datasheet_sample)
    print("Parsed Specs:", parsed_specs)

    # 3. Store in database
    save_to_db(db_file, "OPA820", parsed_specs, manufacturer="Texas Instruments", package="SOIC-8")

    # 4. Synthesize SPICE model
    output_model = "OPA820.subckt"
    generate_subcircuit_from_db(db_file, "OPA820", output_model)

    # Print the resulting netlist
    print("\n--- Generated Netlist Content ---")
    with open(output_model, "r") as f:
        print(f.read())