// User-supplied sketch, saved without behavior changes.
// Station Steward reads its telemetry; this sketch accepts no serial commands.
#include <DHT.h>

#define DHTPIN 2
#define DHTTYPE DHT11
const int trigPin = 9;
const int echoPin = 10;
const int motorPin = 3;
const int joyXPin = A0;
const int joyYPin = A1;
const int joyBtnPin = 4;

const float TEMP_THRESHOLD_ON = 28.0;
const float TEMP_THRESHOLD_OFF = 27.0;
const unsigned long DHT_INTERVAL = 1500;

DHT dht(DHTPIN, DHTTYPE);
unsigned long lastDhtReadTime = 0;
bool fanState = false;
float currentTemp = 0.0;
float currentHum = 0.0;

void setup() {
  Serial.begin(115200);
  pinMode(trigPin, OUTPUT);
  pinMode(echoPin, INPUT);
  pinMode(motorPin, OUTPUT);
  pinMode(joyBtnPin, INPUT_PULLUP);
  digitalWrite(motorPin, LOW);
  dht.begin();
  Serial.println("System Initialized.");
  Serial.println("Reading Ultrasonic, DHT11, Joystick, and controlling Fan...");
}

void loop() {
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);
  long duration = pulseIn(echoPin, HIGH, 30000);
  float distanceCm = -1.0;
  if (duration > 0) distanceCm = (duration * 0.0343) / 2.0;

  int joyX = analogRead(joyXPin);
  int joyY = analogRead(joyYPin);
  int joyBtn = digitalRead(joyBtnPin);

  if (millis() - lastDhtReadTime >= DHT_INTERVAL) {
    lastDhtReadTime = millis();
    float readT = dht.readTemperature();
    float readH = dht.readHumidity();
    if (!isnan(readT) && !isnan(readH)) {
      currentTemp = readT;
      currentHum = readH;
      if (currentTemp >= TEMP_THRESHOLD_ON) {
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
  delay(100);
}
