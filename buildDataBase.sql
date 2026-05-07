-- USERS
CREATE TABLE IF NOT EXISTS users (
    user_id SERIAL PRIMARY KEY,
    username VARCHAR(55) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL
);

-- DEVICES
-- Devices can start unclaimed. Users get access by connecting through user_device.
CREATE TABLE IF NOT EXISTS device (
    device_id SERIAL PRIMARY KEY,
    user_id INTEGER,
    device_code VARCHAR(55) NOT NULL UNIQUE,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE SET NULL
);

-- USER DEVICE CONNECTIONS
CREATE TABLE IF NOT EXISTS user_device (
    user_id INTEGER NOT NULL,
    device_id INTEGER NOT NULL,

    PRIMARY KEY (user_id, device_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (device_id) REFERENCES device(device_id) ON DELETE CASCADE
);

-- SENSORS
CREATE TABLE IF NOT EXISTS sensor (
    sensor_id SERIAL PRIMARY KEY,
    device_id INTEGER NOT NULL,
    name VARCHAR(55) NOT NULL,
    type VARCHAR(55) NOT NULL,
    UNIQUE (device_id, type),
    FOREIGN KEY (device_id) REFERENCES device(device_id) ON DELETE CASCADE
);

-- SENSOR READINGS
CREATE TABLE IF NOT EXISTS sensor_reading (
    reading_id SERIAL PRIMARY KEY,
    sensor_id INTEGER NOT NULL,
    reading_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reading_value DOUBLE PRECISION NOT NULL,
    FOREIGN KEY (sensor_id) REFERENCES sensor(sensor_id) ON DELETE CASCADE
);

INSERT INTO users (username, password_hash)
VALUES
    ('alice', 'fakehash1'),
    ('bob', 'fakehash2');

INSERT INTO device (user_id, device_code)
VALUES
    (1, 'ALPHA-001'),
    (1, 'ALPHA-002'),
    (2, 'BETA-001'),
    (NULL, 'UNCLAIMED-001');

INSERT INTO user_device (user_id, device_id)
SELECT user_id, device_id
FROM device
WHERE user_id IS NOT NULL
ON CONFLICT (user_id, device_id) DO NOTHING;

INSERT INTO sensor (device_id, name, type)
SELECT
    d.device_id,
    sensor_defaults.name,
    sensor_defaults.type
FROM device d
CROSS JOIN (
    VALUES
        ('Temperature Sensor', 'temp'),
        ('Humidity Sensor', 'humidity'),
        ('Pressure Sensor', 'pressure'),
        ('Carbon Dioxide Sensor', 'co2'),
        ('TVOC Sensor', 'tvoc'),
        ('PM1 Sensor', 'pm1.0'),
        ('PM2.5 Sensor', 'pm2.5'),
        ('PM10 Sensor', 'pm10.0')
) AS sensor_defaults(name, type)
ON CONFLICT (device_id, type) DO NOTHING;

INSERT INTO sensor_reading (sensor_id, reading_time, reading_value)
SELECT
    s.sensor_id,
    NOW() - (interval '10 minutes' * gs.i),
    CASE s.type
        WHEN 'temp' THEN 50 + random() * 10
        WHEN 'humidity' THEN 40 + random() * 20
        WHEN 'pressure' THEN 1010 + random() * 5
        WHEN 'co2' THEN 400 + random() * 600
        WHEN 'tvoc' THEN 0.3 + random() * 0.4
        WHEN 'pm1.0' THEN 5 + random() * 10
        WHEN 'pm2.5' THEN 10 + random() * 20
        WHEN 'pm10.0' THEN 15 + random() * 25
    END
FROM sensor s
CROSS JOIN generate_series(1, 36) AS gs(i);
