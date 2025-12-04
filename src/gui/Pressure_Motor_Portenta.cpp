// TODO
// Look into AccelStepper Library for where to put in stuff such as lead screw pitch
// Work out how to reverse (Maybe just making the DIR pin LOW instead of HIGH?)

// FOR PRESSURE CONTROLLER: 
#define PRESSURE_PWM_PIN 13 // PWM Pin for pressure control (0-5V output via LLC)
#define PRESSURE_ADC_PIN A0 // ADC Pin for pressure reading (0-5V input from AliCat via LLC)
#define MAX_PRESSURE_BAR 26.4  // Maximum achievable pressure (corresponds to 68% duty cycle)
#define MIN_DUTY_CYCLE_PERCENT 20.0  // Minimum duty cycle - controller threshold (0 BAR)
#define MAX_DUTY_CYCLE_PERCENT 68.0  // Maximum duty cycle - actual system limit (26.4 BAR)
#define PWM_RESOLUTION 12  // 12-bit PWM (0-4095)
#define PWM_FREQUENCY 1000  // 1kHz PWM frequency
// Voltage scaling for logic level converter
#define PORTENTA_VOLTAGE_MAX 3.3  // Portenta max voltage
#define ALICAT_VOLTAGE_MAX 5.0    // Alicat max voltage

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

constexpr uint32_t steps_per_mm = ((200 * 16) / 2) * 4.25; // ((200*16)/2)*4.25  (((Steps per rotation of motor * MicroSteps)/Lead of screw)*GearBox). = 13,600
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
int reveivedDist = 0;
long initialPosition = 0; //Used to store the starting position for movement tracking
int lastProgressPercent = -1; //Used to track the last reported progress percentage
String inputString = "";
unsigned long movementStartTime = 0; // Track when movement started
unsigned long movementTimeout = 0; // Track movement timeout value
AccelStepper stepper = AccelStepper(stepper.DRIVER, STEP_PIN, DIR_PIN); //Creates a stepper object, with the driver, step pin and direction pin

// Pressure controller variables
float currentPressure = 0.0;  // Current pressure reading in BAR
float targetPressure = 0.0;   // Target pressure in BAR
bool pressureControlEnabled = false;

// Pressure smoothing: rolling average over last 1 second
const int PRESSURE_BUFFER_SIZE = 4;  // 4 readings at 0.25s intervals = 1 second
float pressureBuffer[PRESSURE_BUFFER_SIZE] = {0};
int pressureBufferIndex = 0;
int pressureBufferCount = 0;  // Track how many readings we've collected

// Stall detection variables
long lastPosition = 0;
unsigned long lastPositionChangeTime = 0;

void debugLog(const String& message) {
  Serial.print("DEBUG: ");
  Serial.println(message);
}

// Pressure controller functions
void setPressure(float pressureBar) {
  if (pressureBar < 0 || pressureBar > MAX_PRESSURE_BAR) {
    Serial.println("ERROR: Pressure out of range (0-26.4 BAR)");
    return;
  }
  
  targetPressure = pressureBar;
  pressureControlEnabled = true;
  
  // Apply calibration compensation
  // Empirical relationship: Actual = 1.16 × Input - 0.2
  // To get desired pressure: Input = (Desired + 0.2) / 1.16
  float compensatedPressure = (pressureBar + 0.2) / 1.16;
  
  // Clamp compensated pressure to valid range
  compensatedPressure = constrain(compensatedPressure, 0, MAX_PRESSURE_BAR);
  
  // Convert compensated pressure to PWM duty cycle (20-68% range)
  // 0 BAR = 20% duty cycle (controller minimum threshold)
  // 26.4 BAR = 68% duty cycle (actual system maximum)
  float dutyCycleRange = MAX_DUTY_CYCLE_PERCENT - MIN_DUTY_CYCLE_PERCENT;  // 68% - 20% = 48%
  float dutyCyclePercent = MIN_DUTY_CYCLE_PERCENT + (compensatedPressure / MAX_PRESSURE_BAR) * dutyCycleRange;
  
  // Convert duty cycle percentage to PWM value (12-bit: 0-4095)
  int pwmValue = (int)((dutyCyclePercent / 100.0) * (1 << PWM_RESOLUTION));
  
  // Clamp PWM value to valid range (20-68% of max)
  int minPwmValue = (int)((MIN_DUTY_CYCLE_PERCENT / 100.0) * (1 << PWM_RESOLUTION));  // 20% of 4095 = 819
  int maxPwmValue = (int)((MAX_DUTY_CYCLE_PERCENT / 100.0) * (1 << PWM_RESOLUTION));  // 68% of 4095 = 2785
  pwmValue = constrain(pwmValue, minPwmValue, maxPwmValue);
  
  // Calculate actual voltage output (for debugging)
  float actualVoltage = (pwmValue / (float)(1 << PWM_RESOLUTION)) * PORTENTA_VOLTAGE_MAX;
  
  analogWrite(PRESSURE_PWM_PIN, pwmValue);
  
  debugLog("Pressure request: " + String(pressureBar) + " BAR → compensated: " + String(compensatedPressure, 2) + " BAR (" + String(dutyCyclePercent, 1) + "% duty, " + String(actualVoltage, 2) + "V, PWM: " + String(pwmValue) + ")");
  Serial.println("PRESSURE_SET:" + String(pressureBar));
}

float readPressure() {
  // Read ADC value (0-4095 for 12-bit)
  int adcValue = analogRead(PRESSURE_ADC_PIN);
  
  // Convert ADC to voltage (0-3.3V range)
  float voltage = (adcValue / (float)(1 << 12)) * PORTENTA_VOLTAGE_MAX;
  
  // Voltage-to-pressure mapping based on actual measured values:
  // 0.48V = 0 BAR (or Off)
  // 2.4V = 50 BAR
  // Linear interpolation: pressure = (voltage - 0.48) / (2.4 - 0.48) * 50
  const float VOLTAGE_MIN = 0.48;  // Voltage at 0 BAR
  const float VOLTAGE_MAX = 2.4;    // Voltage at 50 BAR
  const float PRESSURE_FULL_SCALE = 50.0;  // Full scale pressure (BAR)
  
  float pressure;
  if (voltage <= VOLTAGE_MIN) {
    // Below minimum voltage = 0 BAR (off)
    pressure = 0.0;
  } else if (voltage >= VOLTAGE_MAX) {
    // At or above maximum voltage = 50 BAR (but we'll clamp to MAX_PRESSURE_BAR for display)
    pressure = PRESSURE_FULL_SCALE;
  } else {
    // Linear interpolation between 0.48V and 2.4V
    pressure = ((voltage - VOLTAGE_MIN) / (VOLTAGE_MAX - VOLTAGE_MIN)) * PRESSURE_FULL_SCALE;
  }
  
  // Apply linear correction based on calibration measurements:
  // Measured: 0 BAR reads as 0.6 BAR, 5 BAR reads as 5.7 BAR, 10 BAR reads as 11 BAR, 25 BAR reads as 26.4 BAR
  // Linear fit: Reading = 1.032 * Actual + 0.6
  // Therefore: Actual = (Reading - 0.6) / 1.032
  const float CORRECTION_OFFSET = 0.6;
  const float CORRECTION_GAIN = 1.032;
  pressure = (pressure - CORRECTION_OFFSET) / CORRECTION_GAIN;
  
  // Ensure pressure doesn't go negative after correction
  if (pressure < 0.0) {
    pressure = 0.0;
  }
  
  // Clamp to maximum setpoint range (0-26.4 BAR) for display
  currentPressure = constrain(pressure, 0.0, MAX_PRESSURE_BAR);
  
  return currentPressure;
}

void disablePressureControl() {
  pressureControlEnabled = false;
  analogWrite(PRESSURE_PWM_PIN, 0);  // Set to true 0% duty cycle (completely off for safety)
  debugLog("Pressure control disabled (0% duty cycle)");
  Serial.println("PRESSURE_DISABLED");
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
  
  // Initialize pressure controller - SAFETY FIRST!
  pinMode(PRESSURE_PWM_PIN, OUTPUT);
  analogWriteResolution(PWM_RESOLUTION);  // Set 12-bit resolution BEFORE writing PWM
  analogWrite(PRESSURE_PWM_PIN, 0);  // Immediately set to 0% duty cycle (0 BAR) for safety
  pinMode(PRESSURE_ADC_PIN, INPUT);  // Set ADC pin for pressure reading
  analogReadResolution(12);  // Set ADC resolution to 12-bit (0-4095)
  
  // Note: Using default PWM frequency (Portenta H7 default is typically 500-1000 Hz)
  
  debugLog("Pressure pin initialized to 0% duty cycle (0 BAR)");
  
  // Initialize pressure to 0 (redundant but safe)
  setPressure(0.0);
  
  debugLog("Pressure controller initialized");
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
    // Only send handshake if we're not in the middle of a movement
    if (moveFinished == 1) {
      Serial.println("ARDUINO_READY");
      debugLog("Periodic handshake sent - system ready for commands");
    } else {
      debugLog("Periodic handshake skipped - movement in progress");
    }
    lastHandshake = millis();
  }
  
  // Read pressure periodically (every 250ms) and apply rolling average
  static unsigned long lastPressureRead = 0;
  if (millis() - lastPressureRead > 250) {
    // Read raw pressure
    float rawPressure = readPressure();
    
    // Add to rolling buffer
    pressureBuffer[pressureBufferIndex] = rawPressure;
    pressureBufferIndex = (pressureBufferIndex + 1) % PRESSURE_BUFFER_SIZE;
    if (pressureBufferCount < PRESSURE_BUFFER_SIZE) {
      pressureBufferCount++;
    }
    
    // Calculate average of buffer (last 1 second = 4 readings)
    float sum = 0.0;
    for (int i = 0; i < pressureBufferCount; i++) {
      sum += pressureBuffer[i];
    }
    float averagedPressure = sum / pressureBufferCount;
    
    // Update current pressure and send averaged value
    currentPressure = averagedPressure;
    Serial.println("PRESSURE_READING:" + String(averagedPressure, 2));
    lastPressureRead = millis();
  }

  // Manual serial data checking (since serialEvent() doesn't work on Portenta)
  while (Serial.available()) {
    char inChar = (char)Serial.read();
    debugLog("Received char: " + String(inChar));
    if (inChar == '\n') {
      stringComplete = true;
      debugLog("String complete flag set");
      debugLog("Complete input string: '" + inputString + "'");
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
    // Check for PRESSURE_OFF command (HIGHEST PRIORITY - Safety first!)
    else if (inputString.indexOf("PRESSURE_OFF") != -1) {
      debugLog("PRESSURE_OFF command received - EMERGENCY SHUTDOWN");
      disablePressureControl();
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
    // Check for PRESSURE command
    else if (inputString.indexOf("PRESSURE:") != -1) {
      debugLog("PRESSURE command received");
      int pressureIndex = inputString.indexOf("PRESSURE:");
      float pressureValue = inputString.substring(pressureIndex + 9).toFloat();
      setPressure(pressureValue);
    }
    // Check for movement command (SPEED:DIST format)
    else if (inputString.indexOf("SPEED:") != -1 && inputString.indexOf(";DIST:") != -1) {
      debugLog("Movement command received - parsing speed and distance");
      
      // Parse speed and distance
      int speedIndex = inputString.indexOf("SPEED:");
      int distIndex = inputString.indexOf(";DIST:");
      debugLog("Speed index: " + String(speedIndex) + ", Distance index: " + String(distIndex));
      
      receivedSpeed = inputString.substring(speedIndex + 6, distIndex).toInt();
      reveivedDist = inputString.substring(distIndex + 6).toInt();
      
      debugLog("Parsed values - Speed: " + String(receivedSpeed) + ", Distance: " + String(reveivedDist));
      
      Serial.print("Received speed: ");
      Serial.println(receivedSpeed);
      Serial.print("Received distance: ");
      Serial.println(reveivedDist);
      
      // Execute movement
      debugLog("Calling executeMovement function");
      
      executeMovement(receivedSpeed, reveivedDist);
      
      debugLog("Movement tracking started from position: " + String(initialPosition));
    } else {
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
}

void homing() {
  Serial.println("Stepper is Homing...");
  debugLog("Starting homing sequence");
  
  // Check current switch state
  int switchState = digitalRead(backOpticalSwitchPin);
  debugLog("Current optical switch state: " + String(switchState ? "HIGH" : "LOW"));
  
  stepper.setMaxSpeed(10000); // Set a reasonable max speed for homing
  stepper.setSpeed(-10000);    // Negative for homing direction
  debugLog("Set homing speed to -10000");

  // If switch is already triggered, move away first
  if (switchState == HIGH) {
    debugLog("Switch already triggered - moving away first");
    stepper.setSpeed(200);
    while (digitalRead(backOpticalSwitchPin)) {
      stepper.runSpeed();
    }
    debugLog("Moved away from switch");
  }

  // Move until switch is triggered
  debugLog("Moving towards optical switch...");
  while (!digitalRead(backOpticalSwitchPin)) {
    stepper.runSpeed(); // Constant speed, no acceleration
  }
  debugLog("Optical switch triggered - reached home position");

  stepper.setCurrentPosition(0);
  debugLog("Set current position to 0");

  // Move off the switch slowly
  stepper.setSpeed(200); // Move away from switch
  debugLog("Moving away from switch at speed 200");
  while (digitalRead(backOpticalSwitchPin)) {
    stepper.runSpeed();
  }
  debugLog("Moved away from switch");

  stepper.setCurrentPosition(0);
  Serial.println("Homing Complete!");
  homed = true;  // Set homed flag to true
  Serial.println("ARDUINO_READY");  // Signal ready for next command
  debugLog("Homing sequence completed successfully");
}

void executeMovement(int speed, int distance) {
  debugLog("Executing movement - Speed: " + String(speed) + ", Distance: " + String(distance));
  
  // Calculate travel distance in steps
  long travelSteps = distance * steps_per_mm;
  
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
    }
    else {
      inputString += inChar;
    }
  }
}