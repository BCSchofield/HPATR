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

// ── Ramp config ───────────────────────────────────────────────
#define RAMP_DURATION_US  5000000UL  // 5 seconds
#define RAMP_UPDATE_US      20000UL  // recompute speed every 20 ms (250 steps over ramp)

// ─────────────────────────────────────────────────────────────
TMC5160Stepper driver(CS_PIN, R_SENSE);

float         currentRPM    = 0.0;
float         startRPM      = 0.0;
float         targetRPM     = 0.0;
bool          running       = false;
bool          ramping       = false;
long          halfPeriodUs  = 0;
unsigned long rampStartTime  = 0;
unsigned long lastRampUpdate = 0;
unsigned long lastRPMReport  = 0;
String        inputBuffer    = "";

void computeHalfPeriod() {
  if (currentRPM <= 0.0) { halfPeriodUs = 0; return; }
  float stepsPerSec = (currentRPM * STEPS_PER_REV * MICROSTEPS) / 60.0;
  halfPeriodUs = (long)(500000.0 / stepsPerSec);
}

void startRamp(float target) {
  // Start from at least 1 RPM so motor begins stepping immediately
  startRPM      = (currentRPM < 1.0) ? 1.0 : currentRPM;
  currentRPM    = startRPM;
  targetRPM     = target;
  rampStartTime = micros();
  lastRampUpdate = 0;   // force immediate first ramp update
  ramping       = true;
  running       = true;
  computeHalfPeriod();  // valid non-zero halfPeriodUs from startRPM >= 1
}

void setup() {
  Serial.begin(115200);

  pinMode(EN_PIN,   OUTPUT);
  pinMode(DIR_PIN,  OUTPUT);
  pinMode(STEP_PIN, OUTPUT);

  digitalWrite(EN_PIN,  HIGH);  // HIGH = disabled until spin command received
  digitalWrite(DIR_PIN, LOW);

  SPI.begin();
  driver.begin();

  driver.toff(5);
  driver.blank_time(24);
  driver.rms_current(MOTOR_CURRENT);
  driver.microsteps(MICROSTEPS);
  driver.en_pwm_mode(false);
  driver.pwm_autoscale(true);

  Serial.println("RPM controller ready");
}

void loop() {
  // Non-blocking serial read
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      inputBuffer.trim();
      if (inputBuffer.startsWith("RPM:")) {
        float rpm = inputBuffer.substring(4).toFloat();
        if (rpm > 0.0) {
          if (!running) digitalWrite(EN_PIN, LOW);  // enable driver
          startRamp(rpm);
          Serial.print("Ramping to RPM: ");
          Serial.println(rpm);
        }
      } else if (inputBuffer == "STOP") {
        running      = false;
        ramping      = false;
        currentRPM   = 0.0;
        halfPeriodUs = 0;
        digitalWrite(EN_PIN, HIGH);  // disable driver
        Serial.println("Stopped");
      }
      inputBuffer = "";
    } else {
      inputBuffer += c;
    }
  }

  // Ramp update — time-based so it works even when starting from 0 RPM.
  // Must run BEFORE the early return so halfPeriodUs gets set on the first tick.
  if (running && ramping) {
    unsigned long now = micros();
    if (now - lastRampUpdate >= RAMP_UPDATE_US) {
      lastRampUpdate = now;
      unsigned long elapsed = now - rampStartTime;
      if (elapsed >= RAMP_DURATION_US) {
        currentRPM = targetRPM;
        ramping    = false;
      } else {
        float t    = (float)elapsed / (float)RAMP_DURATION_US;
        currentRPM = startRPM + (targetRPM - startRPM) * t;
      }
      computeHalfPeriod();
    }
  }

  // Report current RPM to GUI every 250 ms
  if (running) {
    unsigned long now = micros();
    if (now - lastRPMReport >= 250000UL) {
      lastRPMReport = now;
      Serial.print("RPM_ACTUAL:");
      Serial.println(currentRPM, 1);
    }
  }

  if (!running || halfPeriodUs <= 0) return;

  digitalWrite(STEP_PIN, HIGH);
  delayMicroseconds(halfPeriodUs);
  digitalWrite(STEP_PIN, LOW);
  delayMicroseconds(halfPeriodUs);
}
