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

float targetRPM = 100.0;        // <<<< START LOW, increase once working

// ─────────────────────────────────────────────────────────────
TMC5160Stepper driver(CS_PIN, R_SENSE);

void setup() {
  Serial.begin(115200);

  pinMode(EN_PIN,   OUTPUT);
  pinMode(DIR_PIN,  OUTPUT);
  pinMode(STEP_PIN, OUTPUT);

  digitalWrite(EN_PIN,  LOW);   // LOW = enable driver
  digitalWrite(DIR_PIN, LOW);   // change to HIGH to reverse direction

  SPI.begin();
  driver.begin();

  driver.toff(5);
  driver.blank_time(24);
  driver.rms_current(MOTOR_CURRENT);
  driver.microsteps(MICROSTEPS);
  driver.en_pwm_mode(false);     // StealthChop - quiet
  driver.pwm_autoscale(true);

  Serial.println("Motor starting...");
  Serial.print("Target RPM: ");
  Serial.println(targetRPM);
}

void loop() {
  float stepsPerSec  = (targetRPM * STEPS_PER_REV * MICROSTEPS) / 60.0;
  long  halfPeriodUs = (long)(500000.0 / stepsPerSec);

  digitalWrite(STEP_PIN, HIGH);
  delayMicroseconds(halfPeriodUs);
  digitalWrite(STEP_PIN, LOW);
  delayMicroseconds(halfPeriodUs);
}
