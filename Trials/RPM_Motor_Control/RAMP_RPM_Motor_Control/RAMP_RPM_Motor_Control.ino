// RAMP_RPM_Motor_Control.ino
//
// Non-blocking step/dir ramp using micros() — no Timer1 interrupts.
// Identical logic to REAL_RPM_Motor_Control.ino but without blocking
// delayMicroseconds(), so loop() stays free for serial + ramp updates.
//
// Serial protocol (115200 baud):
//   Receive:  RPM:xxx.x\n   — ramp to target RPM over 5 seconds
//             STOP\n        — stop, disable driver
//   Send:     RPM_READY\n           — on boot
//             RPM_ACTUAL:xxx.x\n   — current RPM every 200 ms
//             STOPPED\n            — after STOP command

#include <TMCStepper.h>
#include <SPI.h>

// ── Pin assignments ───────────────────────────────────────────────────────────
#define EN_PIN    4
#define DIR_PIN   3
#define STEP_PIN  2
#define CS_PIN    10

// ── Driver config ─────────────────────────────────────────────────────────────
#define R_SENSE        0.022f
#define MOTOR_CURRENT  1500

// ── Motion config ─────────────────────────────────────────────────────────────
#define STEPS_PER_REV  200
#define MICROSTEPS     32

// ── Ramp config ───────────────────────────────────────────────────────────────
#define RAMP_DURATION_US  5000000UL   // 5 second ramp
#define RAMP_UPDATE_US      20000UL   // recalculate speed every 20 ms

// ─────────────────────────────────────────────────────────────────────────────
TMC5160Stepper driver(CS_PIN, R_SENSE);

float         currentRPM     = 0.0;
float         startRPM       = 0.0;
float         targetRPM      = 0.0;
bool          running        = false;
bool          ramping        = false;
long          halfPeriodUs   = 0;
unsigned long rampStartTime  = 0;
unsigned long lastRampUpdate = 0;
unsigned long lastStepUs     = 0;
unsigned long lastReportMs   = 0;
bool          stepHigh       = false;
String        inputBuffer    = "";

void computeHalfPeriod() {
  if (currentRPM <= 0.0) { halfPeriodUs = 0; return; }
  float stepsPerSec = (currentRPM * STEPS_PER_REV * MICROSTEPS) / 60.0;
  halfPeriodUs = (long)(500000.0 / stepsPerSec);
}

void startRamp(float target) {
  startRPM      = (currentRPM < 1.0) ? 1.0 : currentRPM;
  currentRPM    = startRPM;
  targetRPM     = target;
  rampStartTime = micros();
  lastRampUpdate = 0;
  ramping       = true;
  running       = true;
  computeHalfPeriod();
}

void setup() {
  Serial.begin(115200);

  pinMode(EN_PIN,   OUTPUT);
  pinMode(DIR_PIN,  OUTPUT);
  pinMode(STEP_PIN, OUTPUT);

  digitalWrite(EN_PIN,  HIGH);
  digitalWrite(DIR_PIN, HIGH);
  digitalWrite(STEP_PIN, LOW);

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

void loop() {
  // ── Serial command parsing ────────────────────────────────────────────────
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      inputBuffer.trim();
      if (inputBuffer.startsWith("RPM:")) {
        float rpm = inputBuffer.substring(4).toFloat();
        if (rpm > 0.0) {
          if (!running) digitalWrite(EN_PIN, LOW);
          startRamp(rpm);
          Serial.print("Ramping to RPM: "); Serial.println(rpm);
        }
      } else if (inputBuffer == "STOP") {
        running      = false;
        ramping      = false;
        currentRPM   = 0.0;
        halfPeriodUs = 0;
        digitalWrite(EN_PIN, HIGH);
        Serial.println("STOPPED");
      }
      inputBuffer = "";
    } else {
      inputBuffer += c;
    }
  }

  // ── Ramp update ───────────────────────────────────────────────────────────
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

  // ── Non-blocking step generation ──────────────────────────────────────────
  if (running && halfPeriodUs > 0) {
    unsigned long now = micros();
    if (now - lastStepUs >= (unsigned long)halfPeriodUs) {
      lastStepUs = now;
      stepHigh = !stepHigh;
      digitalWrite(STEP_PIN, stepHigh);
    }
  }

  // ── RPM report every 200 ms ───────────────────────────────────────────────
  unsigned long now = millis();
  if (now - lastReportMs >= 200UL) {
    lastReportMs = now;
    Serial.print("RPM_ACTUAL:"); Serial.println(currentRPM, 1);
  }
}
