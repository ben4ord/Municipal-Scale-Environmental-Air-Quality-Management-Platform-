import psycopg2
from awscrt import io, mqtt, auth, http
from awsiot import mqtt_connection_builder
import time as t
import json
import time


# Define ENDPOINT, CLIENT_ID, PATH_TO_CERTIFICATE, PATH_TO_PRIVATE_KEY, PATH_TO_AMAZON_ROOT_CA_1, MESSAGE, TOPIC, and RANGE
ENDPOINT = "a3jzbxh9k27w0l-ats.iot.us-east-1.amazonaws.com"
CLIENT_ID = "listener"
PATH_TO_CERTIFICATE = "certificates/d04edff2b04c62616622270e804ffaf174042141c08b02e3ccf9744430a8c481-certificate.pem.crt"
PATH_TO_PRIVATE_KEY = "certificates/d04edff2b04c62616622270e804ffaf174042141c08b02e3ccf9744430a8c481-private.pem.key"
PATH_TO_AMAZON_ROOT_CA_1 = "certificates/AmazonRootCA1.pem"
TOPIC = "airPollution"
RANGE = 10

SENSOR_TYPE_MAP = {
    "temp": "temp",
    "humidity": "humidity",
    "pressure": "pressure",
    "co2": "co2",
    "tvoc": "tvoc",
    "vocc": "tvoc",
    "pm1.0": "pm1.0",
    "pm1": "pm1.0",
    "pm2.5": "pm2.5",
    "pm25": "pm2.5",
    "pm10.0": "pm10.0",
    "pm10": "pm10.0"
}

DEFAULT_SENSORS = {
    "temp": "Temperature Sensor",
    "humidity": "Humidity Sensor",
    "pressure": "Pressure Sensor",
    "co2": "Carbon Dioxide Sensor",
    "tvoc": "TVOC Sensor",
    "pm1.0": "PM1 Sensor",
    "pm2.5": "PM2.5 Sensor",
    "pm10.0": "PM10 Sensor"
}


# Database connection helper
def insert_reading(device_code, sensor_type, value):
    conn = psycopg2.connect(
        database="airpollution",
        user="postgres",
        password="0810",
        host="localhost",
        port="5432"
    )
    cur = conn.cursor()

    try:
        # Get or create the unclaimed device.
        cur.execute(
            """
            SELECT device_id
            FROM device
            WHERE device_code = %s
            """,
            (device_code,)
        )

        result = cur.fetchone()

        # No device found need to make a new one
        if result is None:
            cur.execute(
                """
                INSERT INTO device (device_code)
                VALUES (%s)
                RETURNING device_id
                """,
                (device_code,)
            )
            device_id = cur.fetchone()[0]
            print(f"Created unclaimed device {device_code} with ID {device_id}")

            for default_type, name in DEFAULT_SENSORS.items():
                cur.execute(
                    """
                    INSERT INTO sensor (device_id, name, type)
                    VALUES (%s, %s, %s)
                    """,
                    (device_id, name, default_type)
                )
        else:
            device_id = result[0]

        # Lookup sensor ID by device and type so readings go to the correct device.
        cur.execute(
            """
            SELECT sensor_id
            FROM sensor
            WHERE device_id = %s AND type = %s
            """,
            (device_id, sensor_type)
        )
        result = cur.fetchone()

        if result is None:
            sensor_name = DEFAULT_SENSORS.get(sensor_type)
            if sensor_name is None:
                print(f"Unknown sensor type '{sensor_type}' for device {device_code}")
                conn.rollback()
                return

            cur.execute(
                """
                INSERT INTO sensor (device_id, name, type)
                VALUES (%s, %s, %s)
                RETURNING sensor_id
                """,
                (device_id, sensor_name, sensor_type)
            )
            sensor_id = cur.fetchone()[0]
            print(f"Created sensor '{sensor_type}' for device {device_code}")
        else:
            sensor_id = result[0]

        print(f"Inserting Device ID: {device_id} Sensor ID: {sensor_id} Value: {value}")

        # Insert reading
        cur.execute(
            """
            INSERT INTO sensor_reading (sensor_id, reading_time, reading_value)
            VALUES (%s, NOW(), %s)
            """,
            (sensor_id, value)
        )
        conn.commit()
    except (psycopg2.Error, TypeError, ValueError) as e:
        conn.rollback()
        print(f"Failed to insert reading for device {device_code}: {e}")
    finally:
        cur.close()
        conn.close()



# MQTT message callback
def message_callback_unpack(topic, payload, **kwargs):
    print("MESSAGE RECEIVED")
    try:
        # parse json data from AWS IOT Core
        data = json.loads(payload.decode("utf-8"))
        print(data)
    except json.JSONDecodeError as e:
        print("Invalid JSON:", e)
        return

    device_code = data.get("device_id", data.get("device_code"))
    if device_code is None:
        print("Message missing device_id")
        return

    inserted_sensor_types = set()

    # Create insert for data base
    for payload_key, sensor_type in SENSOR_TYPE_MAP.items():
        if payload_key in data:
            if sensor_type in inserted_sensor_types:
                continue

            insert_reading(device_code, sensor_type, data[payload_key])
            inserted_sensor_types.add(sensor_type)





# Configure MQTT client Subscribe to topic
def subscribe_to_topic():
    # Spin up resources
    event_loop_group = io.EventLoopGroup(1)
    host_resolver = io.DefaultHostResolver(event_loop_group)
    client_bootstrap = io.ClientBootstrap(event_loop_group, host_resolver)
    mqtt_connection = mqtt_connection_builder.mtls_from_path(
            endpoint=ENDPOINT,
            cert_filepath=PATH_TO_CERTIFICATE,
            pri_key_filepath=PATH_TO_PRIVATE_KEY,
            client_bootstrap=client_bootstrap,
            ca_filepath=PATH_TO_AMAZON_ROOT_CA_1,
            client_id=CLIENT_ID,
            clean_session=False,
            keep_alive_secs=30
            )
    # Connect to AWS IoT Core
    print(f"Connecting to {ENDPOINT}...")
    connect_future = mqtt_connection.connect()
    connect_future.result()
    print("Connected!")

    print(f"Subscribing to topic '{TOPIC}'...")
    subscribe_future, packet_id = mqtt_connection.subscribe(
        topic=TOPIC,
        qos=mqtt.QoS.AT_LEAST_ONCE,
        callback=message_callback_unpack
        )
    subscribe_result = subscribe_future.result()
    print(f"Subscribed with QoS: {subscribe_result['qos']}")


    # Keep the script running to listen for messages
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Disconnecting...")
        mqtt_connection.disconnect()
        print("Disconnected.")

if __name__ == '__main__':
    subscribe_to_topic()
