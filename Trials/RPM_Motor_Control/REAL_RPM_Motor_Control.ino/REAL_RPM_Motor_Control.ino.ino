#include <TMCStepper.h>
#include <SPI.h>

// ── Pin assignments ───────────────────────────────────────────
#define EN_PIN    4
#define DIR_PIN   3
#define STEP_PIN  2
#define CS_PIN    10
// MOSI=D11, MISO=D12, SCK=D13 used automatically by SPI.begin()

// ── Driver config ─────────────────────────────────────────────
#define R_SENSE       0.022f   // TMC5160T Plus sense resistor
#define MOTOR_CURRENT 1500     // mA RMS — HH17-101 rated 2A/phase

// ── Motion config ─────────────────────────────────────────────
#define STEPS_PER_REV  200     // 1.8 degree motor
#define MICROSTEPS     32

// ── State ─────────────────────────────────────────────────────
bool motorRunning  = false;
long halfPeriodUs  = 0;        // pre-computed, only updated on RPM command

// ─────────────────────────────────────────────────────────────
TMC5160Stepper driver(CS_PIN, R_SENSE);

void setup() {
  Serial.begin(115200);

  pinMode(EN_PIN,   OUTPUT);
  pinMode(DIR_PIN,  OUTPUT);
  pinMode(STEP_PIN, OUTPUT);

  digitalWrite(EN_PIN,  HIGH);  // HIGH = driver disabled until commanded
  digitalWrite(DIR_PIN, LOW);

  SPI.begin();
  driver.begin();

  driver.toff(5);
  driver.blank_time(24);
  driver.rms_current(MOTOR_CURRENT);
  driver.microsteps(MICROSTEPS);
  driver.en_pwm_mode(false);
  driver.pwm_autoscale(true);

  Serial.println("RPM_READY");
}

// ── Serial command parser ─────────────────────────────────────
// Accepts:  RPM:xxx.x\n   — set RPM and start motor
//           STOP\n        — stop motor
void handleSerial() {
  if (!Serial.available()) return;
  String line = Serial.readStringUntil('\n');
  line.trim();

  if (line.startsWith("RPM:")) {
    float val = line.substring(4).toFloat();
    if (val > 0.0) {
      // Compute once here — loop uses the cached integer value
      float stepsPerSec = (val * STEPS_PER_REV * MICROSTEPS) / 60.0;
      halfPeriodUs  = (long)(500000.0 / stepsPerSec);
      motorRunning  = true;
      digitalWrite(EN_PIN, LOW);   // enable driver
      Serial.print("RPM_SET:");
      Serial.println(val);
    }
  } else if (line == "STOP") {
    motorRunning = false;
    digitalWrite(EN_PIN, HIGH);    // disable driver
    Serial.println("MOTOR_STOPPED");
  }
}

void loop() {
  handleSerial();

  if (!motorRunning) {
    delay(1);
    return;
  }

  digitalWrite(STEP_PIN, HIGH);
  delayMicroseconds(halfPeriodUs);
  digitalWrite(STEP_PIN, LOW);
  delayMicroseconds(halfPeriodUs);
}
