// RAMP_RPM_Motor_Control.ino
//
// Step pulses are generated entirely in hardware by Timer1.
//
// STEP must be wired to pin 9 (PB1 = OC1A).  In CTC mode with COM1A0 set, the
// timer flips that pin on every compare match without involving the CPU, so
// nothing loop() does — Serial prints included — can disturb the step train.
// This replaced a micros()-polled software stepper, where the 200 ms telemetry
// print stalled the loop for ~100-300 us and produced an audible 5 Hz click.
//
// Linear RPM ramp (constant angular acceleration), recalculated every 10 ms.
//
// Serial protocol (115200 baud):
//   Receive:  RPM:xxx.x\n   — ramp to target RPM over RAMP_DURATION_US
//             STOP\n        — stop, disable driver
//   Send:     RPM_READY\n           — on boot
//             RPM_ACTUAL:xxx.x\n   — current RPM every 200 ms
//             STOPPED\n            — after STOP command

#include <TMCStepper.h>
#include <SPI.h>

// ── Pin assignments ───────────────────────────────────────────────────────────
#define EN_PIN    4
#define DIR_PIN   3
#define STEP_PIN  9   // MUST be 9 — this is OC1A, the only Timer1 output pin
                      // that is free (OC1B is pin 10, used here for SPI CS)
#define CS_PIN    10

// ── Driver config ─────────────────────────────────────────────────────────────
#define R_SENSE        0.022f
#define MOTOR_CURRENT  1800       // mA RMS — 23HS26-2004H rated 2A/phase

// ── Motion config ─────────────────────────────────────────────────────────────
#define STEPS_PER_REV  200
#define MICROSTEPS     8

// ── Ramp config ───────────────────────────────────────────────────────────────
#define RAMP_DURATION_US  10000000UL  // 10 second ramp
#define RAMP_UPDATE_US      10000UL   // recalculate speed every 10 ms

// ── Timer1 config ─────────────────────────────────────────────────────────────
// Prescaler 8 gives a 2 MHz tick (0.5 us).  The pin toggles twice per step, so
// with OCR1A as TOP:  OCR1A + 1 = TIMER_HZ / (2 * stepsPerSec).
// For the values above that reduces to OCR1A = 37500 / rpm - 1, which stays
// inside Timer1's 16 bits from about 0.6 RPM upwards.
#define TIMER_PRESCALER  8
#define TIMER_HZ         (F_CPU / TIMER_PRESCALER)

// ─────────────────────────────────────────────────────────────────────────────
TMC5160Stepper driver(CS_PIN, R_SENSE);

float         currentRPM         = 0.0;
float         startRPM           = 0.0;
float         targetRPM          = 0.0;
bool          running            = false;
bool          ramping            = false;
unsigned long rampStartTime      = 0;
unsigned long lastRampUpdate     = 0;
unsigned long lastReportMs       = 0;
String        inputBuffer        = "";

// Timer ticks between pin toggles for a given speed, clamped to Timer1's range.
uint16_t rpmToOcr(float rpm) {
  if (rpm <= 0.0) return 0xFFFF;
  float stepsPerSec = (rpm * STEPS_PER_REV * MICROSTEPS) / 60.0;
  long  ocr = (long)(((float)TIMER_HZ / (2.0 * stepsPerSec)) + 0.5) - 1;
  if (ocr < 1)     ocr = 1;        // faster than the timer can resolve
  if (ocr > 65535) ocr = 65535;    // slower than 16 bits allows
  return (uint16_t)ocr;
}

void setStepRate(float rpm) {
  uint16_t ocr = rpmToOcr(rpm);
  uint8_t sreg = SREG;
  cli();                           // 16-bit registers need an atomic access
  OCR1A = ocr;
  // If the counter is already past the new TOP it would run to 0xFFFF and wrap
  // before matching — up to a 32 ms stall.  Restart the count instead.
  if (TCNT1 > ocr) TCNT1 = 0;
  SREG = sreg;
}

// Connect/disconnect the step pin from the timer.  While disconnected the pin
// reverts to normal port control and is held low.
void stepOutput(bool on) {
  if (on) {
    TCCR1A |= (1 << COM1A0);       // toggle OC1A on compare match
  } else {
    TCCR1A &= ~(1 << COM1A0);
    PORTB  &= ~(1 << PB1);         // PB1 == pin 9 — hold STEP low
  }
}

void startRamp(float target) {
  startRPM       = (currentRPM < 1.0) ? 1.0 : currentRPM;
  currentRPM     = startRPM;
  targetRPM      = target;
  rampStartTime  = micros();
  lastRampUpdate = 0;
  ramping        = true;
  running        = true;
  setStepRate(startRPM);
  stepOutput(true);
}

void stopMotor() {
  stepOutput(false);
  running      = false;
  ramping      = false;
  currentRPM   = 0.0;
  digitalWrite(EN_PIN, HIGH);      // disable driver
}

void setup() {
  Serial.begin(115200);

  pinMode(EN_PIN,   OUTPUT);
  pinMode(DIR_PIN,  OUTPUT);
  pinMode(STEP_PIN, OUTPUT);       // OC1A needs its DDR bit set to drive the pin

  digitalWrite(EN_PIN,  HIGH);
  digitalWrite(DIR_PIN, HIGH);
  digitalWrite(STEP_PIN, LOW);

  // Timer1: CTC (TOP = OCR1A), prescaler 8, output pin left detached until a
  // speed is commanded.  No compare interrupt is enabled — the toggle is
  // performed by the output-compare hardware itself.
  TCCR1A = 0;
  TCCR1B = 0;
  TCNT1  = 0;
  OCR1A  = 0xFFFF;
  TCCR1B |= (1 << WGM12) | (1 << CS11);

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
        stopMotor();
        Serial.println("STOPPED");
      }
      inputBuffer = "";
    } else {
      inputBuffer += c;
    }
  }

  // ── Ramp update (linear RPM = constant angular acceleration) ────────────
  if (running && ramping) {
    unsigned long now = micros();
    if (now - lastRampUpdate >= RAMP_UPDATE_US) {
      lastRampUpdate = now;
      unsigned long elapsed = now - rampStartTime;
      if (elapsed >= RAMP_DURATION_US) {
        currentRPM   = targetRPM;
        ramping      = false;
      } else {
        float t    = (float)elapsed / (float)RAMP_DURATION_US;
        currentRPM = startRPM + (targetRPM - startRPM) * t;
      }
      setStepRate(currentRPM);
    }
  }

  // ── RPM report every 200 ms ───────────────────────────────────────────────
  // Safe at any rate now: the step train is generated by Timer1 hardware and
  // is unaffected by however long this takes.
  unsigned long now = millis();
  if (now - lastReportMs >= 200UL) {
    lastReportMs = now;
    Serial.print("RPM_ACTUAL:"); Serial.println(currentRPM, 1);
  }
}
