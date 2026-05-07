#include "PMS.h"
#include "SparkFunBME280.h"
#include "SparkFunCCS811.h"
#include "esp_sleep.h"
#include <Wire.h>
#include <SD.h>
#include <SPI.h>
#include <ArduinoJson.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <MQTTClient.h>

#define CS_PIN 25
#define MISO_PIN 19
#define MOSI_PIN 23
#define CLK_PIN 18

#define GREEN_LED 32
#define YELLOW_LED 33
#define RED_LED 26

#define CCS811_ADDR 0x5B

#define DEVICE_ID "test_id"

HardwareSerial mySerial(2);

PMS pms(mySerial);
PMS::DATA data;

BME280 tmp_sensor;
CCS811 co2_sensor(CCS811_ADDR);


// ------- Wifi Stuff -------
const char* ssid = "Username";
const char* password = "Password";
// --------------------------

// ------- AWS Stuff -------
const char* AWS_ENDPOINT = "endpoint";

WiFiClientSecure net;
MQTTClient client(256);

// Root CA
const char rootCert[] PROGMEM = R"EOF(
-----BEGIN CERTIFICATE-----

-----END CERTIFICATE-----
)EOF";

// Device Cert
const char deviceCert[] PROGMEM = R"EOF(
-----BEGIN CERTIFICATE-----

-----END CERTIFICATE-----
)EOF";

// Private Key
const char privateKey[] PROGMEM = R"EOF(
-----BEGIN RSA PRIVATE KEY-----

-----END RSA PRIVATE KEY-----
)EOF";
// -------------------------

// ------- Task Handles -------
static TaskHandle_t powerTaskHandle = NULL;
static TaskHandle_t dataTaskHandle = NULL;
static TaskHandle_t mqttTaskHandle = NULL;
// ----------------------------

// ------- Data Variables -------
float temp;
float humidity;
float pressure;
uint16_t co2 = 0;
uint16_t tvoc = 0;
uint16_t pm1_0;
uint16_t pm2_5;
uint16_t pm10_0;
// ------------------------------


// Connect to AWS
void connectAWS() {
  net.setCACert(rootCert);
  net.setCertificate(deviceCert);
  net.setPrivateKey(privateKey);

  client.begin(AWS_ENDPOINT, 8883, net);
  client.setKeepAlive(60);

  Serial.print("Connecting to AWS IoT...");
  while (!client.connect("esp32-client")) {
    Serial.print(".");
    delay(500);
  }
  Serial.println("\nConnected!");

  client.subscribe("test");
}


void messageHandler(String& topic, String& payload) {
  Serial.println("Incoming message:");
  Serial.println(payload);
}


void adjustLights() {
  if (pm1_0 >= 25 || pm2_5 >= 35 || pm10_0 >= 155) {
    digitalWrite(GREEN_LED, LOW);
    digitalWrite(YELLOW_LED, LOW);
    digitalWrite(RED_LED, HIGH);
  } else if (pm1_0 >= 10 || pm2_5 >= 12 || pm10_0 >= 54) {
    digitalWrite(GREEN_LED, LOW);
    digitalWrite(YELLOW_LED, HIGH);
    digitalWrite(RED_LED, LOW);
  } else {
    digitalWrite(GREEN_LED, HIGH);
    digitalWrite(YELLOW_LED, LOW);
    digitalWrite(RED_LED, LOW);
  }
}


void dataTask(void* pvParameters) {
  vTaskDelay(pdMS_TO_TICKS(30000));  // PMS warmup
  while (true) {
    vTaskDelay(pdMS_TO_TICKS(10000));

    temp = tmp_sensor.readTempF();
    humidity = tmp_sensor.readFloatHumidity();
    pressure = tmp_sensor.readFloatPressure();

    co2_sensor.readAlgorithmResults();
    co2 = co2_sensor.getCO2();
    tvoc = co2_sensor.getTVOC();

    // Flush stale PMS frames accumulated during the delay, then read a fresh one
    while (mySerial.available()) mySerial.read();
    unsigned long pmsStart = millis();
    bool pmsOk = false;
    while (millis() - pmsStart < 1500) {
      if (pms.read(data)) { pmsOk = true; break; }
      vTaskDelay(pdMS_TO_TICKS(10));
    }
    if (pmsOk) {
      pm1_0 = data.PM_AE_UG_1_0;
      pm2_5 = data.PM_AE_UG_2_5;
      pm10_0 = data.PM_AE_UG_10_0;
    } else {
      Serial.println("PMS read failed");
    }

    adjustLights();
    writeResults();
  }
}


void powerTask(void* pvParameters) {
  vTaskDelay(pdMS_TO_TICKS(32000)); // wait for PMS warmup + first dataTask read
  while (true) {
    vTaskDelay(pdMS_TO_TICKS(60000));  // Run for 1 minute
    Serial.println("Sleeping for 1 Minute...");

    pms.sleep();
    vTaskSuspend(dataTaskHandle);
    vTaskSuspend(mqttTaskHandle);

    digitalWrite(GREEN_LED, LOW);
    digitalWrite(YELLOW_LED, LOW);
    digitalWrite(RED_LED, LOW);

    vTaskDelay(pdMS_TO_TICKS(1000));
    esp_sleep_enable_timer_wakeup(60ULL * 1000000ULL);  // Sleep for 1 minute
    esp_light_sleep_start();
    Serial.println("Waking up...");

    // Resumes here after wake — let PMS warm up before resuming publishers
    pms.wakeUp();
    Serial.println("Waiting 30 seconds for sensor warmup...");

    vTaskResume(dataTaskHandle);
    vTaskDelay(pdMS_TO_TICKS(30000));  // Wait for PMS warmup
    vTaskResume(mqttTaskHandle);
  }
}


void mqttTask(void* pvParameters) {
  vTaskDelay(pdMS_TO_TICKS(32000));  // wait for PMS warmup + first dataTask read
  while (true) {
    if (!client.connected()) {
      Serial.print("Reconnecting to AWS...");
      while (!client.connect("esp32-client")) {
        Serial.print(".");
        delay(500);
      }
      Serial.println(" reconnected.");
    }
    client.loop();

    StaticJsonDocument<128> doc;
    doc["device_id"] = DEVICE_ID;
    doc["temp"] = temp;
    doc["humidity"] = humidity;
    doc["pressure"] = pressure;
    doc["co2"] = co2;
    doc["tvoc"] = tvoc;
    doc["pm1.0"] = pm1_0;
    doc["pm2.5"] = pm2_5;
    doc["pm10.0"] = pm10_0;

    String jsonStr;
    serializeJson(doc, jsonStr);
    client.publish("airPollution", jsonStr);
    Serial.println("Published: " + jsonStr);

    vTaskDelay(pdMS_TO_TICKS(10000));
  }
}


void writeResults() {
  File file = SD.open("/logs/sensorLog.txt", FILE_APPEND);
  if (!file) {
    Serial.println("Failed to open file for writing!");
    return;
  }
  file.println("Device ID: " + String(DEVICE_ID));
  file.println("Temperature: " + String(temp));
  file.println("Humidity: " + String(humidity));
  file.println("Pressure: " + String(pressure));
  file.println("CO2: " + String(co2));
  file.println("TVOC: " + String(tvoc));
  file.println("PM1.0: " + String(pm1_0));
  file.println("PM2.5: " + String(pm2_5));
  file.println("PM10.0: " + String(pm10_0));
  file.println();
  file.close();
}


void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("Serial OK");

  mySerial.begin(9600, SERIAL_8N1, 17, 16);
  Serial.println("mySerial OK");

  pinMode(GREEN_LED, OUTPUT);
  pinMode(YELLOW_LED, OUTPUT);
  pinMode(RED_LED, OUTPUT);

  pms.wakeUp();
  Serial.println("Waking up PMS");
  delay(3000);

  SPI.begin(CLK_PIN, MISO_PIN, MOSI_PIN, CS_PIN);
  delay(500);
  bool sdMounted = false;
  for (int i = 0; i < 5; i++) {
    if (SD.begin(CS_PIN)) { sdMounted = true; break; }
    Serial.println("SD mount failed, retrying (" + String(i + 1) + "/5)...");
    delay(1000);
  }
  if (!sdMounted) {
    Serial.println("SD mount failed after 5 attempts, continuing without SD.");
  } else {
    Serial.println("SD mounted!");
  }

  Wire.begin();
  tmp_sensor.setI2CAddress(0x77);
  if (tmp_sensor.beginI2C() == false) {
    Serial.println("The temp sensor did not respond. Please check wiring.");
    while (1)
      ;
  }
  Serial.println("BME280 ready!");

  if (co2_sensor.begin() == false) {
    Serial.println("The co2 sensor did not respond. Please check wiring.");
    while (1)
      ;
  }
  Serial.println("CCS811 ready!");

  if (!SD.exists("/logs")) {
    SD.mkdir("/logs");
  }

  WiFi.begin(ssid, password);
  Serial.print("Connecting to WiFi...");
  while (WiFi.status() != WL_CONNECTED) {
    Serial.print(".");
    delay(300);
  }
  Serial.println("\nWiFi connected.");

  client.onMessage(messageHandler);
  connectAWS();

  Serial.println("Waiting 30 seconds for sensor warmup...");

  xTaskCreate(dataTask,  "DataTask",  8192,  NULL, 1, &dataTaskHandle);
  xTaskCreate(mqttTask,  "MqttTask",  16384, NULL, 1, &mqttTaskHandle);
  xTaskCreate(powerTask, "PowerTask", 4096,  NULL, 1, &powerTaskHandle);
}


void loop() {
}