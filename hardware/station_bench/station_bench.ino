#include <DHT.h>

// --- Pin Definitions ---
// DHT11 Sensor
#define DHTPIN 2
#define DHTTYPE DHT11

// HC-SR04 Ultrasonic Sensor
const int trigPin = 9;
const int echoPin = 10;

// DC Motor Fan (via Transistor Base)
const int motorPin = 7; // D7 drives the transistor/driver control input, not motor power.
// Leave disabled until a suitable driver/transistor circuit and flyback diode are wired.
// A two-wire motor must never connect directly to D7, even with an external battery.
const bool FAN_DRIVER_CONNECTED = false;

// Analog Joystick Module
const int joyXPin = A0;
const int joyYPin = A1;
const int joyBtnPin = 4;

// --- Settings & Thresholds ---
const float TEMP_THRESHOLD_ON = 28.0;   // Turn fan ON at/above this temp (°C)
const float TEMP_THRESHOLD_OFF = 27.0;  // Turn fan OFF below this temp (°C) (1°C hysteresis)
const unsigned long DHT_INTERVAL = 1500; // Read DHT11 every 1.5 seconds

// --- State Variables ---
DHT dht(DHTPIN, DHTTYPE);
unsigned long lastDhtReadTime = 0;
bool fanState = false;
float currentTemp = 0.0;
float currentHum = 0.0;

void setup() {
  Serial.begin(115200);

  // Pin modes
  pinMode(trigPin, OUTPUT);
  pinMode(echoPin, INPUT);
  pinMode(motorPin, FAN_DRIVER_CONNECTED ? OUTPUT : INPUT);
  pinMode(joyBtnPin, INPUT_PULLUP); // Use internal pullup for joystick switch

  // Ensure motor starts off
  if (FAN_DRIVER_CONNECTED) digitalWrite(motorPin, LOW);

  // Initialize temperature sensor
  dht.begin();

  Serial.println("System Initialized.");
  Serial.println("Reading Ultrasonic, DHT11, Joystick, and controlling Fan...");
  if (!FAN_DRIVER_CONNECTED) Serial.println("Fan control disabled: motor driver required.");
}

void loop() {
  // 1. Trigger and read the HC-SR04 Ultrasonic Sensor
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);

  // Pulse timeout set to 30,000 microseconds (~5 meters max range)
  long duration = pulseIn(echoPin, HIGH, 30000);
  float distanceCm = -1.0;
  if (duration > 0) {
    distanceCm = (duration * 0.0343) / 2.0; // Speed of sound conversion
  }

  // 2. Read Joystick Inputs
  int joyX = analogRead(joyXPin);
  int joyY = analogRead(joyYPin);
  int joyBtn = digitalRead(joyBtnPin); // LOW when pressed, HIGH when released

  // 3. Read DHT11 using non-blocking timing (every 1.5 seconds)
  if (millis() - lastDhtReadTime >= DHT_INTERVAL) {
    lastDhtReadTime = millis();

    float readT = dht.readTemperature();
    float readH = dht.readHumidity();

    if (!isnan(readT) && !isnan(readH)) {
      currentTemp = readT;
      currentHum = readH;

      // Hysteresis control logic for the fan motor
      if (!FAN_DRIVER_CONNECTED) {
        fanState = false; // D7 remains an input; sensors and serial telemetry still run.
      } else if (currentTemp >= TEMP_THRESHOLD_ON) {
        fanState = true;
        digitalWrite(motorPin, HIGH);
      } else if (currentTemp < TEMP_THRESHOLD_OFF) {
        fanState = false;
        digitalWrite(motorPin, LOW);
      }
    } else {
      Serial.println("Warning: Failed to read from DHT sensor!");
    }
  }

  // 4. Output telemetry to Serial Monitor
  Serial.print("#Dist: ");
  if (distanceCm >= 0) {
    Serial.print(distanceCm, 1);
    Serial.print(" !cm#");
  } else {
    Serial.print("XX Out of range#");
  }

  Serial.print(" | Temp: ");
  Serial.print(currentTemp, 1);
  Serial.print(" C | Hum: ");
  Serial.print(currentHum, 1);
  Serial.print("% | Fan: ");
  Serial.print(fanState ? "ON " : "OFF");

  Serial.print(" | Joy: [X: ");
  Serial.print(joyX);
  Serial.print(", Y: ");
  Serial.print(joyY);
  Serial.print(", Btn: ");
  Serial.print(joyBtn == LOW ? "DOWN" : "UP");
  Serial.println("]");

  // Small delay between loop iterations for stability
  delay(100);
}
