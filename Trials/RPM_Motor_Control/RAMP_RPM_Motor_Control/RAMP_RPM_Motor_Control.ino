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
// Driver status (SG_RESULT / OTPW / OT / CS_ACTUAL) is polled every
// STATUS_INTERVAL_MS and reported over serial.  If SG_RESULT — a TMC5160
// back-EMF load estimate — drops below STALL_SG_THRESHOLD while the motor is
// past MIN_STALL_CHECK_RPM, the motor is treated as stalled and stopped here
// in firmware, not left to the GUI to notice and react to.
//
// SG_RESULT is unreliable at very low speed (little back-EMF to measure), and
// its relationship to "actually stalled" depends on this motor and its load —
// STALL_SG_THRESHOLD below is a starting guess, not a calibrated value.  Watch
// the live SG readout in the GUI: if it never drops even when you stall the
// shaft by hand, raise the threshold; if it trips during normal running, lower
// it (or raise MIN_STALL_CHECK_RPM if the false trips only happen near
// start-up, where SG_RESULT is still settling).
//
// Serial protocol (115200 baud):
//   Receive:  RPM:xxx.x\n   — ramp to target RPM over RAMP_DURATION_US
//             STOP\n        — stop, disable driver
//   Send:     RPM_READY\n           — on boot
//             RPM_ACTUAL:xxx.x\n    — current RPM every 200 ms
//             MOTOR_STATUS:sg=<0-1023>,otpw=<0/1>,ot=<0/1>,ma=<actual mA>
//                                    — driver status every STATUS_INTERVAL_MS.
//                                     ma is computed from GLOBAL_SCALER + the
//                                     driver's live current-scale register, so
//                                     it reads ~half of MOTOR_CURRENT while
//                                     idle (ihold) and the full value while
//                                     running (irun) — expected, not a fault.
//             STALL_DETECTED:rpm=xxx.x\n
//                                    — SG_RESULT dropped below threshold while
//                                     running at the given RPM; always
//                                     immediately followed by:
//             STOPPED\n             — after STOP command, or after a stall

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

// ── Driver status / stall detection config ────────────────────────────────────
#define STATUS_INTERVAL_MS   300      // how often to poll + report SG/OTPW/OT/current
#define STALL_SG_THRESHOLD    20      // SG_RESULT below this while running = stall.
                                       // Lowered from 50 — that was tripping during
                                       // legitimate near-torque-limit running. TUNE
                                       // against real readings — see note above.
#define MIN_STALL_CHECK_RPM   60      // below this, SG_RESULT is too noisy to trust.
                                       // Raised from an initial 20 — that was tripping
                                       // during normal ramp-up. Provisional: watch the
                                       // live SG number in the GUI through a low-RPM
                                       // ramp and retune once you have real numbers.

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
unsigned long lastStatusMs       = 0;
String        inputBuffer        = "";

// Actual RMS current in mA for a given CS (0-31), reading the driver's live
// GLOBAL_SCALER.  This is a direct port of TMC2160Stepper::cs2rms() — that
// method only ever reads irun(), so it can't tell you the idle (ihold) figure;
// calling it here with cs_actual() gives whichever one the driver is really
// applying right now.
uint16_t csToMilliamps(uint8_t cs) {
  uint16_t scaler = driver.GLOBAL_SCALER();
  if (scaler == 0) scaler = 256;
  uint32_t numerator = (uint32_t)scaler * (cs + 1);
  numerator *= 325;             // V_fs = 0.325 V, scaled by 1000
  numerator >>= 13;             // /256 (GLOBAL_SCALER) and /32 (CS), combined
  numerator *= 1000000UL;
  uint32_t denominator = (uint32_t)(R_SENSE * 1000) * 1414UL;  // 1414 ~= 1000*sqrt(2)
  return denominator ? (numerator / denominator) : 0;
}

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

  // ── Driver status + stall safety check ────────────────────────────────────
  if (now - lastStatusMs >= STATUS_INTERVAL_MS) {
    lastStatusMs = now;
    uint16_t sg   = driver.sg_result();  // TMCStepper: lowercase on the 5160 family
    bool     otpw = driver.otpw();
    bool     ot   = driver.ot();
    uint16_t ma   = csToMilliamps(driver.cs_actual());  // ~half MOTOR_CURRENT while
                                                          // idle (ihold) — that's normal

    Serial.print("MOTOR_STATUS:sg=");   Serial.print(sg);
    Serial.print(",otpw=");             Serial.print(otpw ? 1 : 0);
    Serial.print(",ot=");               Serial.print(ot ? 1 : 0);
    Serial.print(",ma=");               Serial.println(ma);

    // Only trust SG_RESULT once actually turning at a reasonable speed —
    // see the header note on tuning STALL_SG_THRESHOLD / MIN_STALL_CHECK_RPM.
    if (running && currentRPM >= MIN_STALL_CHECK_RPM && sg < STALL_SG_THRESHOLD) {
      float stalledAtRpm = currentRPM;   // stopMotor() below zeroes currentRPM
      stopMotor();
      Serial.print("STALL_DETECTED:rpm="); Serial.println(stalledAtRpm, 1);
      Serial.println("STOPPED");
    }
  }
}
