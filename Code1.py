import mysql.connector
from mysql.connector import Error

def read_mysql_database():
    connection = None
    try:
        connection = mysql.connector.connect(
            host="localhost",
            user="root",
            password="your_password",
            database="eda_library"
        )

        if connection.is_connected():
            cursor = connection.cursor(dictionary=True)  # Returns rows as Python dicts
            
            query = "SELECT model_name, technology_node, status FROM spice_models WHERE status = %s"
            cursor.execute(query, ("verified",))

            # Fetch rows one by one to save memory with large datasets
            for row in cursor.fetchall():
                print(row["model_name"], row["technology_node"])

    except Error as e:
        print(f"Error connecting to MySQL: {e}")
    finally:
        if connection and connection.is_connected():
            cursor.close()
            connection.close()

if __name__ == "__main__":
    read_mysql_database()