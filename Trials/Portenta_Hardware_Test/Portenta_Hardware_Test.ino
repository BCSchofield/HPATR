// Portenta H7 hardware diagnostic — optical switches, TMC5160 driver, motor.
//
// Upload this INSTEAD of Pressure_Motor_Portenta.cpp to test the rig one piece
// at a time.  It never homes and contains no blocking wait loops, so it cannot
// brick itself on a bad switch the way the real firmware could.
//
// Open the Arduino IDE Serial Monitor at 9600 baud, set to "Newline".
//
//   Commands:  f = jog forward (away from home)   b = jog back (toward home)
//              s = stop        d = dump driver registers        h = help
//
// WHAT TO LOOK FOR
//   * SWITCH lines change as you pass something through each slot.
//     If BACK never leaves HIGH, the signal is not reaching pin 5 — regardless
//     of what the LED on the switch module does.  See the ground note below.
//   * DRIVER version should read 0x30 for a TMC5160.  0x00 or 0xFF means SPI
//     is not talking (wiring, CS, or a damaged driver).
//   * With 'f' or 'b', POS must change.  If POS moves but nothing physically
//     turns, the driver is stepping into a disconnected or dead motor.
//   * Jogging AUTO-STOPS as soon as either switch changes state, so it will
//     not drive into an end stop.  Seeing that auto-stop happen proves the
//     entire chain — switch, wiring, terminal board, pin, reaction — works.

// Bump this whenever the command set changes, so the board can tell you which
// build is actually flashed.  "Command does nothing" is nearly always an older
// upload still on the board rather than a fault.
#define BUILD_TAG "build 5 (f b s d p c w x h)"

#include <TMCStepper.h>
#include <AccelStepper.h>

#define EN_PIN     0
#define DIR_PIN    2
#define STEP_PIN   3
#define CS_PIN     6
#define R_SENSE    0.022f

// The real firmware defines these three but then builds the driver with the
// HARDWARE-SPI constructor, so they are never used.  If the driver is actually
// wired to these pins, hardware SPI talks to nothing and every read returns 0.
// We test BOTH here and report which one the chip answers on.
#define SW_MOSI    8
#define SW_MISO   10
#define SW_SCK     9

const int frontOpticalSwitchPin = 1;
const int backOpticalSwitchPin  = 5;

TMC5160Stepper driverHW = TMC5160Stepper(CS_PIN, R_SENSE);
TMC5160Stepper driverSW = TMC5160Stepper(CS_PIN, R_SENSE, SW_MOSI, SW_MISO, SW_SCK);
TMC5160Stepper *driver  = &driverHW;   // repointed at setup if SW SPI wins

AccelStepper  stepper = AccelStepper(stepper.DRIVER, STEP_PIN, DIR_PIN);

int  lastFront = -1, lastBack = -1;
int  jogStartFront = -1, jogStartBack = -1;
long jogSpeed = 0;

// Read the version register over both SPI routes and pick whichever answers.
// version() reads the VERSION field of IOIN; a TMC5160 returns 0x30.  0x00 or
// 0xFF means no data is coming back on MISO at all.
void probeSPI() {
  Serial.println("--- SPI probe ---");
  driverHW.begin();
  uint8_t vHW = driverHW.version();
  Serial.println("  hardware SPI          -> version=0x" + String(vHW, HEX) +
                 (vHW == 0x30 ? "   <== RESPONDING" : ""));

  driverSW.begin();
  uint8_t vSW = driverSW.version();
  Serial.println("  software SPI (8/10/9) -> version=0x" + String(vSW, HEX) +
                 (vSW == 0x30 ? "   <== RESPONDING" : ""));

  if      (vHW == 0x30) { driver = &driverHW; Serial.println("  using HARDWARE SPI"); }
  else if (vSW == 0x30) { driver = &driverSW; Serial.println("  using SOFTWARE SPI"); }
  else {
    Serial.println("  NEITHER responds - the driver has no logic power (VCC_IO),");
    Serial.println("  no common ground, miswired CS/SCK/MOSI/MISO, or is dead.");
  }
}

void dumpDriver() {
  uint8_t  ver    = driver->version();
  uint32_t status = driver->DRV_STATUS();
  Serial.println("DRIVER version=0x" + String(ver, HEX) +
                 (ver == 0x30 ? "  (OK, TMC5160 responding)"
                              : "  (BAD - SPI not talking to the driver)"));
  Serial.println("DRIVER DRV_STATUS=0x" + String(status, HEX));
  Serial.println("DRIVER rms_current=" + String(driver->rms_current()) + "mA" +
                 "  microsteps=" + String(driver->microsteps()) +
                 "   (microsteps=256 when you asked for 16 means the read"
                 " returned zeros)");
}

// ---- pin scanner ---------------------------------------------------------
// On a Portenta HAT Carrier the 40-pin header's numbering is NOT the same as
// Arduino pin numbering, so a switch wired to "header pin 5" is very unlikely
// to be Arduino pin 5.  Reading the wrong pad gives a pullup HIGH that never
// changes — indistinguishable from a dead switch.  Rather than guess at the
// mapping, this watches every pin at once and tells you which one moves.
#define SCAN_MAX_PIN 21
int  scanState[SCAN_MAX_PIN + 1];
bool scanning = false;

void startScan() {
  Serial.println("--- pin scan: watching pins 0.." + String(SCAN_MAX_PIN) + " ---");
  Serial.println("Now block/unblock each switch.  Any pin that CHANGES is the");
  Serial.println("one it is really wired to.  Press 'x' to stop scanning.");
  for (int p = 0; p <= SCAN_MAX_PIN; p++) pinMode(p, INPUT_PULLUP);
  delay(10);
  String low = "";
  for (int p = 0; p <= SCAN_MAX_PIN; p++) {
    scanState[p] = digitalRead(p);
    if (scanState[p] == LOW) low += String(p) + " ";
  }
  // A pin already sitting LOW is being pulled down by something real, which is
  // itself a useful sign of life on that line.
  Serial.println("baseline: pins reading LOW = " + (low.length() ? low : String("(none)")));
  scanning = true;
}

void stopScan() {
  scanning = false;
  Serial.println("--- pin scan stopped (reboot to restore motor pins) ---");
}

// ---- pin walker ----------------------------------------------------------
// The mirror of the scanner, for OUTPUT pins (SCK, MOSI, CS, STEP, DIR, EN).
// Drives one pin at a time as a square wave for a few seconds.  A DC
// multimeter averages a square wave to about half the rail, so the pin you
// are probing reads ~1.6V while it is being walked and 0V or 3.3V otherwise.
// That identifies which Arduino pin number reaches which physical pad, which
// a meter cannot tell you from a steady idle level.
#define WALK_MS 3000
bool walking = false;
int  walkPin = 0;
unsigned long walkStart = 0;

void startWalk() {
  Serial.println("--- pin walk: pins 0.." + String(SCAN_MAX_PIN) + ", " +
                 String(WALK_MS / 1000) + "s each ---");
  Serial.println("Probe a driver pin (SCK/MOSI/CS) with the meter on DC volts.");
  Serial.println("It reads ~1.6V (half rail) ONLY while its pin is walked.");
  Serial.println("WARNING: disconnect anything that DRIVES a pin (switch");
  Serial.println("outputs) first - driving into them risks contention.");
  Serial.println("Press 'x' to stop.");
  walking = true; walkPin = 0; walkStart = millis();
  pinMode(walkPin, OUTPUT);
  Serial.println("walking pin " + String(walkPin));
}

void stopWalk() {
  if (walking) pinMode(walkPin, INPUT);
  walking = false;
  Serial.println("--- pin walk stopped (reboot to restore motor pins) ---");
}

void help() {
  Serial.println("--- " BUILD_TAG " ---");
  Serial.println("--- commands: f=fwd  b=back  s=stop  d=driver  p=SPI probe");
  Serial.println("              c=scan inputs  w=walk outputs  x=stop  h=help ---");
}

void setup() {
  Serial.begin(9600);
  // Bounded wait: never hang if no host ever opens the port.
  unsigned long t0 = millis();
  while (!Serial && millis() - t0 < 5000) { }

  Serial.println();
  Serial.println("=== Portenta hardware diagnostic — " BUILD_TAG " ===");

  pinMode(frontOpticalSwitchPin, INPUT_PULLUP);
  pinMode(backOpticalSwitchPin,  INPUT_PULLUP);
  Serial.println("Switch pins are INPUT_PULLUP: an unconnected pin reads HIGH.");
  Serial.println("So HIGH alone does NOT prove the switch is working — you must");
  Serial.println("see it CHANGE when you block the slot.");

  SPI.begin();
  pinMode(CS_PIN, OUTPUT);  digitalWrite(CS_PIN, HIGH);
  pinMode(EN_PIN, OUTPUT);  digitalWrite(EN_PIN, LOW);
  probeSPI();
  // toff() is what actually turns the output stage on.  If SPI is dead this
  // never lands, toff stays 0, and the motor is completely free to turn by
  // hand no matter how healthy the power rails are.
  driver->toff(5);
  driver->rms_current(2000);
  driver->microsteps(16);
  dumpDriver();

  stepper.setMaxSpeed(4000);
  stepper.setAcceleration(8000);
  stepper.setEnablePin(EN_PIN);
  stepper.setPinsInverted(false, false, true);
  stepper.enableOutputs();

  help();
}

// Read and act on one-letter commands.  This MUST run before the walk block
// below: the walk returns early, so handling commands after it meant 'x' was
// never read and the walk could not be stopped — despite the banner saying so.
void handleCommands() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == 'f' || c == 'b') {
      jogSpeed  = (c == 'f') ? 2000 : -2000;
      // Latch the switch states at the moment jogging starts.  We do not yet
      // know this switch's polarity, so we watch for ANY change rather than
      // for a particular level — that works whichever way round it is wired.
      jogStartFront = digitalRead(frontOpticalSwitchPin);
      jogStartBack  = digitalRead(backOpticalSwitchPin);
      Serial.println(c == 'f' ? "> jog FORWARD (away from home)"
                              : "> jog BACK (toward home)");
    }
    else if (c == 's') { jogSpeed = 0; Serial.println("> stop"); }
    else if (c == 'd') { dumpDriver(); }
    else if (c == 'p') { probeSPI(); }
    else if (c == 'c') { startScan(); }
    else if (c == 'w') { startWalk(); }
    else if (c == 'x') { stopScan(); stopWalk(); }
    else if (c == 'h') { help(); }
    // Anything else (including the newline the Serial Monitor appends) is
    // ignored rather than echoed, so a stray CR/LF cannot look like a fault.
  }
}

void loop() {
  handleCommands();

  // ---- pin walk: square-wave one pin at a time ---------------------------
  if (walking) {
    if (millis() - walkStart > WALK_MS) {
      pinMode(walkPin, INPUT);              // release before moving on
      walkPin++;
      if (walkPin > SCAN_MAX_PIN) { stopWalk(); }
      else {
        pinMode(walkPin, OUTPUT);
        walkStart = millis();
        Serial.println("walking pin " + String(walkPin));
      }
    } else {
      // ~2kHz square wave: fast enough to average cleanly on a DC meter,
      // slow enough that any meter can track it.
      digitalWrite(walkPin, HIGH); delayMicroseconds(250);
      digitalWrite(walkPin, LOW);  delayMicroseconds(250);
    }
    return;   // nothing else runs while walking
  }

  // ---- pin scan: report ANY pin that changes -----------------------------
  if (scanning) {
    for (int p = 0; p <= SCAN_MAX_PIN; p++) {
      int v = digitalRead(p);
      if (v != scanState[p]) {
        Serial.println("PIN " + String(p) + " changed -> " +
                       String(v ? "HIGH" : "LOW") + "   <== THIS IS YOUR PIN");
        scanState[p] = v;
      }
    }
  }

  // ---- switches: report every change immediately -------------------------
  int f = digitalRead(frontOpticalSwitchPin);
  int b = digitalRead(backOpticalSwitchPin);
  if (f != lastFront || b != lastBack) {
    Serial.println("SWITCH front=" + String(f ? "HIGH" : "LOW ") +
                   "  back=" + String(b ? "HIGH" : "LOW ") + "   <-- CHANGED");
    lastFront = f; lastBack = b;
  }

  // ---- 1 Hz heartbeat so you can see it is alive while probing -----------
  static unsigned long lastBeat = 0;
  if (millis() - lastBeat > 1000) {
    Serial.println("STATE front=" + String(f ? "HIGH" : "LOW ") +
                   "  back=" + String(b ? "HIGH" : "LOW ") +
                   "  pos=" + String(stepper.currentPosition()) +
                   "  jog=" + String(jogSpeed));
    lastBeat = millis();
  }

  if (jogSpeed != 0) {
    // Auto-stop the moment either switch changes state.  This protects the
    // hardware (there is no limit logic here otherwise) and is the real
    // end-to-end test: switch -> wiring -> terminal board -> pin -> reaction.
    if (b != jogStartBack || f != jogStartFront) {
      jogSpeed = 0;
      Serial.println("> AUTO-STOP: switch changed while jogging "
                     "(front=" + String(f ? "HIGH" : "LOW") +
                     " back=" + String(b ? "HIGH" : "LOW") + ")");
      Serial.println("  ^ this is the whole signal chain working correctly.");
    } else {
      stepper.setSpeed((float)jogSpeed);
      stepper.runSpeed();
    }
  }
}
