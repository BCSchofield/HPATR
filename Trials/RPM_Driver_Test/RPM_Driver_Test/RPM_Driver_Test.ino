// Uno + TMC5160 driver diagnostic — read-only, no ramp, no stall logic.
//
// Upload this INSTEAD of RAMP_RPM_Motor_Control.ino to find out why the spin
// motor has no torque.  Flash the real firmware straight back afterwards; this
// changes nothing permanent.
//
// Serial Monitor at 115200, line ending "Newline".
//
//   d = dump all driver registers      t = write/read-back test
//   e = toggle driver enable           j = send 1600 step pulses (1 rev)
//   i = re-run driver init             h = help
//
// THE KEY TEST IS 't'.  It writes a value to CHOPCONF and reads it back:
//   * read-back MATCHES  -> SPI writes and reads both work, so the fault is
//                           downstream: the power stage or the enable line.
//   * read-back DIFFERS  -> writes are not landing, so toff never turns the
//                           chopper on and the motor can never hold.
//
// Register-read gotchas that have already caused confusion here:
//   * GLOBAL_SCALER and IHOLD_IRUN are WRITE-ONLY on the TMC5160.  The
//     library's getters return its own shadow copy and never touch the chip,
//     so they look healthy even with the bus unplugged.
//   * CHOPCONF and DRV_STATUS ARE genuinely readable — those are the ones to
//     trust, and the only ones used for the verdicts below.

#define BUILD_TAG "RPM driver diag build 1"

#include <TMCStepper.h>
#include <SPI.h>

#define EN_PIN    4      // active LOW on the TMC5160
#define DIR_PIN   3
#define STEP_PIN  9
#define CS_PIN    10
#define R_SENSE   0.022f
#define MOTOR_CURRENT 1800
#define MICROSTEPS    8

TMC5160Stepper driver(CS_PIN, R_SENSE);
bool enabled = false;

void help() {
  Serial.println(F("--- " BUILD_TAG " ---"));
  Serial.println(F("d=dump  t=write/read-back test  e=toggle enable  j=1600 steps  i=init  h=help"));
}

void dumpAll() {
  Serial.println(F("---------------- driver dump ----------------"));

  uint8_t ver = driver.version();
  Serial.print(F("version      = 0x")); Serial.print(ver, HEX);
  Serial.println(ver == 0x30 ? F("   OK - chip is talking")
                             : F("   BAD - SPI not reaching the chip"));
  if (ver != 0x30) {
    Serial.println(F("Everything below is meaningless while version is wrong."));
  }

  // GSTAT is where the supply/fault flags live - NOT DRV_STATUS.
  uint8_t gstat = driver.GSTAT();
  Serial.print(F("GSTAT        = 0x")); Serial.println(gstat, HEX);
  Serial.print(F("  reset      = ")); Serial.println(driver.reset());
  Serial.print(F("  drv_err    = ")); Serial.print(driver.drv_err());
  Serial.println(F("   <- 1 means the driver shut its output stage off"));
  Serial.print(F("  uv_cp      = ")); Serial.print(driver.uv_cp());
  Serial.println(F("   <- 1 means charge-pump undervoltage (no/low VM)"));

  uint32_t st = driver.DRV_STATUS();
  Serial.print(F("DRV_STATUS   = 0x")); Serial.println(st, HEX);
  if (st == 0UL)          Serial.println(F("  ^ all zeros - reads are not working"));
  if (st == 0xFFFFFFFFUL) Serial.println(F("  ^ all ones  - MISO floating, reads not working"));
  Serial.print(F("  cs_actual  = ")); Serial.print(driver.cs_actual());
  Serial.println(F("   <- 0 means zero current is being applied"));
  Serial.print(F("  sg_result  = ")); Serial.println(driver.sg_result());
  Serial.print(F("  stst       = ")); Serial.print(driver.stst());
  Serial.println(F("   <- 1 = standstill"));
  Serial.print(F("  otpw / ot  = ")); Serial.print(driver.otpw());
  Serial.print(F(" / "));             Serial.println(driver.ot());
  Serial.print(F("  s2ga/s2gb  = ")); Serial.print(driver.s2ga());
  Serial.print(F(" / "));             Serial.print(driver.s2gb());
  Serial.println(F("   <- short to ground"));
  Serial.print(F("  ola / olb  = ")); Serial.print(driver.ola());
  Serial.print(F(" / "));             Serial.print(driver.olb());
  Serial.println(F("   <- open load (coil not connected)"));

  // CHOPCONF is a real read, so toff here is what the CHIP holds, not a shadow.
  uint32_t chop = driver.CHOPCONF();
  Serial.print(F("CHOPCONF     = 0x")); Serial.println(chop, HEX);
  uint8_t toff = driver.toff();
  Serial.print(F("  toff       = ")); Serial.print(toff);
  Serial.println(toff == 0 ? F("   <- ZERO: output stage OFF, motor cannot hold")
                           : F("   <- non-zero: chopper enabled"));
  Serial.print(F("  microsteps = ")); Serial.println(driver.microsteps());

  Serial.print(F("EN_PIN       = ")); Serial.print(enabled ? F("LOW") : F("HIGH"));
  Serial.println(enabled ? F(" (driver ENABLED)") : F(" (driver DISABLED)"));
  Serial.println(F("---------------------------------------------"));
}

// Write a value, read it back off the chip, and say whether it stuck.
void writeTest() {
  Serial.println(F("--- write / read-back test (CHOPCONF is genuinely readable) ---"));
  bool allOk = true;
  const uint8_t probes[] = {3, 5, 7};
  for (uint8_t i = 0; i < 3; i++) {
    driver.toff(probes[i]);
    delay(5);
    uint8_t got = driver.toff();
    Serial.print(F("  wrote toff=")); Serial.print(probes[i]);
    Serial.print(F("  read back=")); Serial.print(got);
    if (got == probes[i]) Serial.println(F("   ok"));
    else { Serial.println(F("   MISMATCH")); allOk = false; }
  }
  driver.toff(5);   // leave the chopper enabled

  Serial.println();
  if (allOk) {
    Serial.println(F("VERDICT: SPI writes AND reads both work."));
    Serial.println(F("  So the bus is fine and the fault is downstream:"));
    Serial.println(F("  the enable line, or a damaged power stage."));
    Serial.println(F("  Next: press 'e' to enable, then 'd' and check cs_actual."));
  } else {
    Serial.println(F("VERDICT: writes are NOT reaching the chip."));
    Serial.println(F("  toff stays at whatever it was, so the output stage never"));
    Serial.println(F("  turns on and the motor cannot hold. Check MOSI (pin 11),"));
    Serial.println(F("  SCK (13) and CS (10) - pin 11 was the shorted one."));
  }
}

void initDriver() {
  driver.begin();
  driver.toff(5);
  driver.blank_time(24);
  driver.rms_current(MOTOR_CURRENT);
  driver.microsteps(MICROSTEPS);
  driver.en_pwm_mode(false);
  driver.pwm_autoscale(true);
  Serial.println(F("driver init done"));
}

void setEnable(bool on) {
  enabled = on;
  digitalWrite(EN_PIN, on ? LOW : HIGH);   // active LOW
  Serial.print(F("> driver "));
  Serial.println(on ? F("ENABLED (EN low) - motor should now feel stiff")
                    : F("DISABLED (EN high) - motor free to turn"));
}

// Manual step pulses.  No Timer1, no ramp, no stall logic - just pulses, so a
// failure here is the driver or the wiring rather than anything clever.
void stepPulses(uint16_t n) {
  Serial.print(F("> sending ")); Serial.print(n); Serial.println(F(" step pulses"));
  for (uint16_t i = 0; i < n; i++) {
    digitalWrite(STEP_PIN, HIGH); delayMicroseconds(500);
    digitalWrite(STEP_PIN, LOW);  delayMicroseconds(500);
  }
  Serial.println(F("> done - did the shaft move?"));
}

void setup() {
  Serial.begin(115200);
  pinMode(EN_PIN,   OUTPUT);
  pinMode(DIR_PIN,  OUTPUT);
  pinMode(STEP_PIN, OUTPUT);
  digitalWrite(EN_PIN,  HIGH);      // start disabled
  digitalWrite(DIR_PIN, HIGH);
  digitalWrite(STEP_PIN, LOW);

  SPI.begin();
  Serial.println();
  Serial.println(F("=== " BUILD_TAG " ==="));
  initDriver();
  dumpAll();
  help();
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if      (c == 'd') dumpAll();
    else if (c == 't') writeTest();
    else if (c == 'e') setEnable(!enabled);
    else if (c == 'j') stepPulses(1600);
    else if (c == 'i') initDriver();
    else if (c == 'h') help();
  }
}
