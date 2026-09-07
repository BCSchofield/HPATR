// Merge term 1
// TODO
// Look into AccelStepper Library for where to put in stuff such as lead screw pitch
// Work out how to reverse (Maybe just making the DIR pin LOW instead of HIGH?)

// PRESSURE CONTROLLER REMOVED
// Pressure and mass flow are now read directly from the Alicat MFC over RS232 by
// the GUI; this board only drives the stepper.  The PWM pin is still held at 0%
// duty at boot so a still-wired pressure controller stays commanded off — if the
// pressure hardware is physically gone, this define and its use in setup() can go.
#define PRESSURE_PWM_PIN 13 // PWM Pin formerly used for pressure control

#include <TMCStepper.h> //Include the TMCStepper library
#include <AccelStepper.h> //Include the AccelStepper library  

#define EN_PIN           0 // Enable pin , IO26 on board     
#define DIR_PIN          2 // Direction pin, IO13 on board  
#define STEP_PIN         3 // Step pin, IO6 on board
#define CS_PIN           6 // Chip select pin, IO4 on board
#define SW_MOSI          8 // Software Master Out Slave In (MOSI)
#define SW_MISO          10 // Software Master In Slave Out (MISO)
#define SW_SCK           9 // Software Slave Clock (SCK)
//#define SERIAL_PORT Serial1 // TMC2208/TMC2224 HardwareSerial port
//#define DRIVER_ADDRESS 0b00 // TMC2209 Driver address according to MS1 and MS2
#define R_SENSE 0.022f // Match to your driver 

// Select your stepper driver type
TMC5160Stepper driver = TMC5160Stepper(CS_PIN, R_SENSE);

constexpr uint32_t steps_per_mm = ((200 * 16) / 2) * 4.25; // ((200*16)/2)*4.25  (((Steps per rotation of motor * MicroSteps)/Lead of screw)*GearBox). = 6,800
const int frontOpticalSwitchPin = 1; //Creates a variable to store the front optical switch pin
const int backOpticalSwitchPin = 5; //Creates a variable to store the back optical switch pin 
long dist; //Creates a variable to store the distance
long travel; //Used to store value entered in the Serial Monitor
int moveFinished = 1; //Used to check if move has been completed
long initialHoming = -1; //Used to home stepper at startup
bool homed = false; //Used to check if stepper has been homed
int lastMillis; //Used to store the last time the motor was updated
bool stringComplete = false; //Used to check if the string has been completed
int receivedSpeed = 0;
float reveivedDist = 0.0f;
long initialPosition = 0; //Used to store the starting position for movement tracking
int lastProgressPercent = -1; //Used to track the last reported progress percentage
String inputString = "";
unsigned long movementStartTime = 0; // Track when movement started
unsigned long movementTimeout = 0; // Track movement timeout value
bool jogMode = false;
int jogDirection = 1;
AccelStepper stepper = AccelStepper(stepper.DRIVER, STEP_PIN, DIR_PIN); //Creates a stepper object, with the driver, step pin and direction pin

// Stall detection variables
long lastPosition = 0;
unsigned long lastPositionChangeTime = 0;

void debugLog(const String& message) {
  Serial.print("DEBUG: ");
  Serial.println(message);
}

void resetMovementState() {
  debugLog("Resetting movement state");
  moveFinished = 1;  // Mark as ready
  stringComplete = false;
  inputString = "";
  receivedSpeed = 0;
  reveivedDist = 0;
  initialPosition = 0;
  lastProgressPercent = -1;
  lastMillis = 0;
  movementStartTime = 0;
  movementTimeout = 0;
  
  // Stop any ongoing movement
  if (stepper.isRunning()) {
    stepper.stop();
    stepper.setCurrentPosition(stepper.currentPosition());  // Maintain current position
  }
  
  debugLog("Movement state reset complete");
}

void setup() {
  SPI.begin(); //Starts the SPI communication
  Serial.begin(9600);  // Initialize serial communication (USB CDC)
  // Initialize UART to Pi (bridge for CAM: commands). Use 115200 for responsiveness
  Serial1.begin(115200);
  inputString.reserve(50); //Saves 50 bytes for input string
  pinMode(frontOpticalSwitchPin, INPUT_PULLUP); // Set the front optical switch pin as INPUT_PULLUP
  pinMode(backOpticalSwitchPin, INPUT_PULLUP); // Set the back optical switch pin as INPUT_PULLUP
  while(!Serial); // Waits for serial port to connect
  Serial.println("ARDUINO_READY"); //Handshake for Python code
  
  pinMode(CS_PIN, OUTPUT); // Sets CS_PIN (Pin 10) as an Output
  digitalWrite(CS_PIN, HIGH); // Writes the CS_PIN (Pin 10) as High
  pinMode(EN_PIN, OUTPUT); // Sets EN_PIN (Pin 9) as an Output
  digitalWrite(EN_PIN, LOW); // Writes the EN_PIN (Pin 9) as Low
  driver.begin(); // Initiate pins and registeries
  driver.toff(5); // Chopper Setting, MAY HAVE TO CHANGE AT A LATER DATE
  Serial.print("DRV_STATUS: "); //Debugging help
  Serial.println(driver.DRV_STATUS(), HEX); // Debugging help
  driver.rms_current(2000); // Set stepper current to 2000mA. The command is the same as command TMC2130.setCurrent(600, 0.11, 0.5);
  driver.en_pwm_mode(0); // Enable extremely quiet stepping (OFF)
  driver.pwm_autoscale(1); // Sets PWM scaling factor to 1
  driver.microsteps(16); // Sets the motor to have 16 microsteps. If changed, alter steps_per_mm variable.
  
  //stepper.setMaxSpeed(500*steps_per_mm);           // !!!!!100mm/s @ 80 steps/mm
  stepper.setAcceleration(1000*steps_per_mm);     // !!!!!2000mm/s^2
  stepper.setEnablePin(EN_PIN);                   // Enables the motor
  stepper.setPinsInverted(false, false, true);    // Sets: StepInvert, DirectionInvert, EnableInvert. StepInvert true = forwards, false = backwards
  stepper.enableOutputs();                        // Enables Stepper output
  
  // Hold the retired pressure control line at 0% duty so a still-wired
  // controller is commanded off and never floats to an unknown setpoint.
  pinMode(PRESSURE_PWM_PIN, OUTPUT);
  analogWrite(PRESSURE_PWM_PIN, 0);
  debugLog("Pressure PWM line held at 0% duty (pressure control retired)");
}

void loop() {
  // Only home once at startup
  if (!homed) {
    homing();
    homed = true;
    Serial.println("ARDUINO_READY"); // Send handshake after homing
  }

  // Send periodic handshake to ensure GUI can detect us
  static unsigned long lastHandshake = 0;
  if (millis() - lastHandshake > 3000) { // Send every 3 seconds
    // Only send handshake if we're not in the middle of a movement or jog
    if (moveFinished == 1 && !jogMode) {
      Serial.println("ARDUINO_READY");
      debugLog("Periodic handshake sent - system ready for commands");
    } else {
      debugLog("Periodic handshake skipped - movement in progress");
    }
    lastHandshake = millis();
  }
  
  // Manual serial data checking (since serialEvent() doesn't work on Portenta)
  while (Serial.available()) {
    char inChar = (char)Serial.read();
    debugLog("Received char: " + String(inChar));
    if (inChar == '\n') {
      stringComplete = true;
      debugLog("String complete flag set");
      debugLog("Complete input string: '" + inputString + "'");
      break; // Process one command per loop() iteration — prevents JOG+STOP merging
    }
    else {
      inputString += inChar;
    }
  }

  // Non-blocking relay from Pi UART back to USB Serial, prefixed as CAM:
  // We read complete lines from Serial1 and forward once a newline is seen
  static String camInbound;
  while (Serial1.available()) {
    char c = (char)Serial1.read();
    if (c == '\n') {
      camInbound.trim();
      if (camInbound.length() > 0) {
        Serial.print("CAM:");
        Serial.println(camInbound);
      }
      camInbound = "";
    } else {
      camInbound += c;
    }
  }

  // Check for new serial command
  if (stringComplete) {
    debugLog("=== COMMAND PROCESSING START ===");
    debugLog("String complete, parsing command...");
    debugLog("Input string: '" + inputString + "'");
    debugLog("Input string length: " + String(inputString.length()));
    
    // Forward any camera command to Pi: lines starting with CAM:
    if (inputString.startsWith("CAM:")) {
      String camLine = inputString.substring(4); // strip CAM:
      camLine.trim();
      // Forward to Serial1 with newline
      Serial1.print(camLine);
      Serial1.print('\n');
    }
    // Check for RESET command
    else if (inputString.indexOf("RESET:") != -1) {
      debugLog("RESET command received - resetting Arduino state");
      resetMovementState(); // Use the new reset function
      Serial.println("ARDUINO_READY");  // Signal ready for next command
    }
    // Check for HOME command
    else if (inputString.indexOf("HOME:") != -1) {
      debugLog("HOME command received - starting homing sequence");
      homing();       // Run homing sequence (always executes)
      debugLog("Homing sequence completed");
    }
    // Check for movement command (SPEED:DIST format)
    else if (inputString.indexOf("SPEED:") != -1 && inputString.indexOf(";DIST:") != -1) {
      debugLog("Movement command received - parsing speed and distance");
      
      // Parse speed and distance
      int speedIndex = inputString.indexOf("SPEED:");
      int distIndex = inputString.indexOf(";DIST:");
      debugLog("Speed index: " + String(speedIndex) + ", Distance index: " + String(distIndex));
      
      receivedSpeed = inputString.substring(speedIndex + 6, distIndex).toInt();
      reveivedDist = inputString.substring(distIndex + 6).toFloat();
      
      debugLog("Parsed values - Speed: " + String(receivedSpeed) + ", Distance: " + String(reveivedDist));
      
      Serial.print("Received speed: ");
      Serial.println(receivedSpeed);
      Serial.print("Received distance: ");
      Serial.println(reveivedDist);
      
      // Execute movement
      debugLog("Calling executeMovement function");
      
      executeMovement(receivedSpeed, reveivedDist);
      
      debugLog("Movement tracking started from position: " + String(initialPosition));
    }
    // Check for JOG command
    else if (inputString.indexOf("JOG:") != -1 && inputString.indexOf(";DIR:") != -1) {
      int jogSpeedIdx = inputString.indexOf("JOG:");
      int jogDirIdx   = inputString.indexOf(";DIR:");
      int jogSpeed    = inputString.substring(jogSpeedIdx + 4, jogDirIdx).toInt();
      jogDirection    = inputString.substring(jogDirIdx + 5).toInt();
      debugLog("JOG command - Speed: " + String(jogSpeed) + ", Dir: " + String(jogDirection));
      stepper.enableOutputs();
      stepper.setMaxSpeed(jogSpeed);
      stepper.setSpeed((float)(jogDirection * jogSpeed));
      jogMode  = true;
      lastMillis = millis();
    }
    // Check for STOP command — emergency stop for jogs AND SPEED:/DIST: moves
    else if (inputString.indexOf("STOP") != -1) {
      debugLog("STOP command received - halting all movement");
      if (jogMode) {
        jogMode = false;
        stepper.setSpeed(0);
        long finalPos = stepper.currentPosition();
        stepper.setCurrentPosition(finalPos);
        Serial.println("JOG_POS:" + String(finalPos));
      }
      // Abort any move in progress.  STOP used to handle jogs only, so the
      // GUI's emergency button could not halt a traverse move at all.
      // Clearing the target as well as the flag makes the monitor block below
      // fail both its conditions, halting on this loop iteration rather than
      // decelerating over a distance.
      if (moveFinished == 0) {
        stepper.setSpeed(0);
        stepper.moveTo(stepper.currentPosition());   // distanceToGo() -> 0
        moveFinished = 1;
        movementTimeout = 0;
        // Releases the GUI's move state (travel bar, watchdog, Start button).
        // NOTE: the GUI credits the full commanded distance on this message, so
        // the travel counter will over-read after an abort — re-home afterwards.
        Serial.println("MOVEMENT_COMPLETE");
      }
      Serial.println("ARDUINO_READY");
    }
    else {
      debugLog("Unknown command format: '" + inputString + "'");
      Serial.println("ARDUINO_READY"); // Signal ready for next command
    }
    
    inputString = ""; // Clear the input string
    stringComplete = false; // Clear the string complete variable
    debugLog("Command processing complete, waiting for next command");
    debugLog("=== COMMAND PROCESSING END ===");
  }

  // Monitor movement progress (non-blocking)
  if (moveFinished == 0 && stepper.distanceToGo() != 0) {
    // Check if stepper is actually running
    if (!stepper.isRunning()) {
      debugLog("Stepper not running - enabling outputs and starting");
      stepper.enableOutputs();
      stepper.run();  // Try to start movement
    } else {
      stepper.run();  // Continue movement
    }
    
    // Stall detection - check if position hasn't changed in 2 seconds
    long currentPosition = stepper.currentPosition();
    
    if (currentPosition != lastPosition) {
      lastPosition = currentPosition;
      lastPositionChangeTime = millis();
    } else if (millis() - lastPositionChangeTime > 2000) {
      // Position hasn't changed in 2 seconds - motor has stalled or completed
      long targetPosition = stepper.targetPosition();
      long distanceTraveled = abs(currentPosition - initialPosition);
      long totalDistance = abs(targetPosition - initialPosition);
      int progressPercent = (totalDistance > 0) ? (distanceTraveled * 100) / totalDistance : 0;
      
      Serial.println("STALL_DETECTED: Pos=" + String(currentPosition) + " Target=" + String(targetPosition) + " Progress=" + String(progressPercent) + "%");
      Serial.println("MOVEMENT_COMPLETE");
      moveFinished = 1;
      Serial.println("ARDUINO_READY");
      return;  // Exit early
    }
    
    // Update progress every 100ms (fast enough for small movements, but keeps serial overhead low)
    if (millis() - lastMillis > 100) {
      long targetPosition = stepper.targetPosition();
      long totalDistance = abs(targetPosition - initialPosition);
      long distanceTraveled = abs(currentPosition - initialPosition);
      
      if (totalDistance > 0 && distanceTraveled > 0) {
        int progressPercent = (distanceTraveled * 100) / totalDistance;
        
        // Only send serial update if progress actually changed (reduces serial spam)
        if (progressPercent > lastProgressPercent && progressPercent <= 100) {
          Serial.println("DEBUG: Movement progress: " + String(progressPercent) + "%");
          lastProgressPercent = progressPercent;
        }
      }
      
      lastMillis = millis();
    }
  }
  // Check if movement is complete
  else if (moveFinished == 0 && stepper.distanceToGo() == 0) {
    // Only mark as complete if we actually moved and the stepper is not running
    if (!stepper.isRunning()) {
      long currentPosition = stepper.currentPosition();
      long targetPosition = stepper.targetPosition();
      long distanceTraveled = abs(currentPosition - initialPosition);
      
      debugLog("Checking completion - Current: " + String(currentPosition) + ", Target: " + String(targetPosition) + ", Traveled: " + String(distanceTraveled));
      
      // Check if we've moved a reasonable distance (at least 10% of target or 100 steps minimum)
      long targetDistance = abs(targetPosition - initialPosition);
      long minMovement = max(100L, targetDistance / 10);  // At least 100 steps or 10% of target
      
      if (distanceTraveled >= minMovement) {
        debugLog("Movement completed! Distance traveled: " + String(distanceTraveled) + " steps");
        Serial.println("MOVEMENT_COMPLETE");
        moveFinished = 1;  // Mark movement as finished
        
        // Update position tracking for next movement
        initialPosition = targetPosition;  // Update initial position for next movement
        
        Serial.println("ARDUINO_READY");  // Signal ready for next command
        debugLog("Movement marked as complete, ready for next command");
      } else {
        // Don't spam the terminal - only log occasionally
        static unsigned long lastLogTime = 0;
        if (millis() - lastLogTime > 2000) {  // Log every 2 seconds
          debugLog("Movement in progress - distance traveled: " + String(distanceTraveled) + " of " + String(targetDistance) + " steps");
          lastLogTime = millis();
        }
      }
    } else {
      // Stepper is still running, don't check completion yet
      debugLog("Stepper still running, waiting for completion...");
    }
  }
  
  // Safety timeout check - if movement takes too long, force completion
  if (moveFinished == 0 && millis() - movementStartTime > movementTimeout && movementTimeout > 0) {
    debugLog("Movement timeout reached - forcing completion");
    Serial.println("MOVEMENT_TIMEOUT");
    moveFinished = 1;

    // Reset stepper state
    long targetPosition = stepper.targetPosition();
    stepper.setCurrentPosition(targetPosition);
    initialPosition = targetPosition;

    Serial.println("ARDUINO_READY");
    debugLog("Movement timeout - system reset and ready");
  }

  // Jog mode: constant-speed movement driven by held GUI button
  if (jogMode) {
    long currentPos = stepper.currentPosition();
    bool atLimit = (jogDirection > 0 && currentPos >= 986000) ||
                   (jogDirection < 0 && currentPos <= 0);
    if (atLimit) {
      jogMode = false;
      stepper.setSpeed(0);
      stepper.setCurrentPosition(currentPos);
      Serial.println("JOG_POS:" + String(currentPos));
      Serial.println("JOG_LIMIT");
      Serial.println("ARDUINO_READY");
    } else {
      stepper.runSpeed();
      if (millis() - lastMillis > 100) {
        Serial.println("JOG_POS:" + String(currentPos));
        lastMillis = millis();
      }
    }
  }
}

// Homing limits are expressed in STEPS, not milliseconds.  The two phases run
// at wildly different speeds (200 vs 10000 steps/s), so any single time limit
// is either far too tight for the slow back-off or useless for the fast search.
// At 6800 steps/mm the back-off covers only 0.029 mm/s, so a 30 s limit would
// abort after 0.88 mm and blame a healthy switch.
#define HOMING_BACKOFF_MAX_STEPS   68000L    // 10 mm — far more than clearing a slot
#define HOMING_SEARCH_MAX_STEPS  1100000L    // beyond the 986000-step axis limit
// Backstop only, for the case where the motor is not moving at all.
#define HOMING_ABSOLUTE_MAX_MS    300000UL

// Run the stepper at its current speed until `pin` reads `target`.
// Returns false if it travels `maxSteps` without seeing it.
//
// Every homing wait MUST go through here.  The bare `while (digitalRead(...))`
// loops this replaces had no bound and no output, so any switch that never
// reached the expected state hung the board forever: silent, deaf to serial,
// and driving the motor into a hard stop the whole time.  A dead or miswired
// switch presented as "the GUI can't find the board on COMx", which is
// impossible to diagnose from the outside.
bool runUntilSwitch(int pin, int target, long maxSteps) {
  long startPos = stepper.currentPosition();
  unsigned long start = millis();
  unsigned long lastBeat = start;
  while (digitalRead(pin) != target) {
    if (labs(stepper.currentPosition() - startPos) > maxSteps) return false;
    if (millis() - start > HOMING_ABSOLUTE_MAX_MS) return false;
    // Heartbeat so a connected host can see homing is alive and moving,
    // rather than having to guess at silence.  Also reports travel, which
    // distinguishes "switch never changed" from "motor never moved".
    if (millis() - lastBeat > 1000) {
      Serial.println("HOMING_PROGRESS:pos=" + String(stepper.currentPosition()) +
                     ",moved=" + String(stepper.currentPosition() - startPos));
      lastBeat = millis();
    }
    stepper.runSpeed();
  }
  return true;
}

// Abandon homing without hanging.  Stops the motor and reports why; loop()
// then marks the board homed and sends ARDUINO_READY, so the GUI can still
// connect and surface the fault instead of timing out on a dead port.
// The axis is NOT homed after this — re-home with HOME: once it is fixed.
void homingFailed(const String& why) {
  stepper.setSpeed(0);
  stepper.stop();
  Serial.println("HOMING_FAILED: " + why);
  debugLog("Homing aborted: " + why);
}

void homing() {
  Serial.println("Stepper is Homing...");
  debugLog("Starting homing sequence");

  // Check current switch state
  int switchState = digitalRead(backOpticalSwitchPin);
  debugLog("Current optical switch state: " + String(switchState ? "HIGH" : "LOW"));

  stepper.setMaxSpeed(10000); // Set a reasonable max speed for homing

  // If switch is already triggered, move away first.
  // NOTE: pin is INPUT_PULLUP, so a disconnected, unpowered or reversed-polarity
  // switch also reads HIGH and lands here — hence the timeout below, which is
  // what distinguishes "already at home" from "no working switch at all".
  if (switchState == HIGH) {
    debugLog("Switch already triggered - moving away first");
    stepper.setSpeed(200);
    if (!runUntilSwitch(backOpticalSwitchPin, LOW, HOMING_BACKOFF_MAX_STEPS)) {
      homingFailed("back switch stayed HIGH after backing off 10mm - check it is "
                   "wired to pin 5, shares ground with the board, and is not "
                   "inverted (pin 5 reads HIGH when disconnected)");
      return;
    }
    debugLog("Moved away from switch");
  }

  // Move until switch is triggered.
  // Re-assert the search direction: the back-off phase above leaves the speed
  // at +200 (away from home).  Without this the search crawled further away
  // from the switch it was waiting for and could never finish.
  stepper.setSpeed(-10000);
  debugLog("Moving towards optical switch at speed -10000...");
  if (!runUntilSwitch(backOpticalSwitchPin, HIGH, HOMING_SEARCH_MAX_STEPS)) {
    homingFailed("back switch never triggered - carriage travelled the full axis "
                 "without reaching home");
    return;
  }
  debugLog("Optical switch triggered - reached home position");

  stepper.setCurrentPosition(0);
  debugLog("Set current position to 0");

  // Move off the switch slowly
  stepper.setSpeed(200); // Move away from switch
  debugLog("Moving away from switch at speed 200");
  if (!runUntilSwitch(backOpticalSwitchPin, LOW, HOMING_BACKOFF_MAX_STEPS)) {
    homingFailed("back switch stayed HIGH after backing off home");
    return;
  }
  debugLog("Moved away from switch");

  stepper.setCurrentPosition(0);
  Serial.println("Homing Complete!");
  homed = true;  // Set homed flag to true
  Serial.println("ARDUINO_READY");  // Signal ready for next command
  debugLog("Homing sequence completed successfully");
}

void executeMovement(int speed, float distance) {
  debugLog("Executing movement - Speed: " + String(speed) + ", Distance: " + String(distance));

  // Calculate travel distance in steps
  long travelSteps = (long)round((float)distance * steps_per_mm);
  
  // Get current position and calculate target position
  long currentPos = stepper.currentPosition();
  long targetPos = currentPos + travelSteps;
  
  // Validate that we don't exceed the 72.5mm limit (986000 steps)
  if (targetPos < 0 || targetPos > 986000) {
    Serial.println("ERROR: Movement would exceed limits (0-72.5mm from home)");
    debugLog("Current position: " + String(currentPos) + ", Target would be: " + String(targetPos) + ", Limit: 986000");
    return;
  }
  
  // Ensure stepper is properly configured
  stepper.enableOutputs();  // Enable motor outputs
  stepper.setMaxSpeed(speed);
  stepper.setAcceleration(1000 * steps_per_mm);
  
  // Set up position tracking for new experiment
  initialPosition = currentPos;  // Store current position as starting point
  moveFinished = 0;  // Movement in progress
  lastMillis = millis();  // Start time for progress updates
  lastProgressPercent = -1;  // Track last reported progress
  
  // Reset stall detection
  lastPosition = currentPos;
  lastPositionChangeTime = millis();
  
  Serial.println("MOVEMENT_START: Pos=" + String(initialPosition) + " Target=" + String(targetPos) + " Steps=" + String(travelSteps));
  
  // Move to target position (relative movement)
  stepper.moveTo(targetPos);
  
  // Add safety timeout - if movement takes too long, force completion
  movementStartTime = millis();
  // Calculate timeout: (distance in mm * 1000ms/s) / (speed in steps/s) * (steps_per_mm) + 30 second buffer
  movementTimeout = ((long)distance * 1000L * steps_per_mm) / (long)speed + 30000;  // Expected time + 30 second buffer
  debugLog("Movement timeout set to: " + String(movementTimeout) + "ms");
}

void serialEvent() {
  while (Serial.available()) {
    char inChar = (char)Serial.read();
    debugLog("Received char: " + String(inChar));
    if (inChar == '\n') {
      stringComplete = true;
      debugLog("String complete flag set");
      break;
    }
    else {
      inputString += inChar;
    }
  }
}