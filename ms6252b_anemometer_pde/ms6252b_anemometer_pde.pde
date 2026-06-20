// Data capture program for MASTECH MS6252B Digital Anemometer

import processing.serial.*;

Serial meter;

int[] values;
int nValues = 800;
int baudRate = 9600;

String portName = "";
String status = "serial not connected";
StringBuilder rawLine = new StringBuilder();
StringBuilder strippedLine = new StringBuilder();

int[] rawTail = new int[96];
int rawTailWrite = 0;
int rawTailCount = 0;

float windSpeed = 0;
float temperatureC = 0;
float humidityPct = 0;
int rawWind = 0;
int rawTemperature = 0;
int rawHumidity = 0;
String lastFrameHex = "";
boolean hasSerialValue = false;
boolean binaryMode = false;
boolean mouseFallback = false;

int[] packetTail = new int[13];
int packetTailWrite = 0;
int packetTailCount = 0;

void setup(){
  size(900,500); 
  nValues = width;
  values = new int[nValues];
  for (int i=0; i<nValues; i++){
    values[i] = height - 40; 
  }
  textFont(createFont("Monospaced", 12));
  connectSerial();
}

//------------------------------------------
void draw(){
  readSerial();

  background(255); 
  textSize(18); 

  float sourceValue = windSpeed;
  if (!hasSerialValue && mouseFallback) {
    sourceValue = map(mouseY, height - 1, 0, 0, 30);
  }

  for (int i=0; i<(nValues-1); i++){
    values[i] = values[i+1];
  }
  values[nValues-1] = valueToY(sourceValue);
  
  stroke(0);
  noFill();
  beginShape(); 
  for (int i=0; i<nValues; i++){
    vertex(i, values[i]); 
  }
  endShape(); 

  drawOverlay(sourceValue);
}

//------------------------------------------
void connectSerial() {
  if (meter != null) {
    meter.stop();
    meter = null;
  }

  String[] ports = Serial.list();
  println("Serial ports:");
  for (int i = 0; i < ports.length; i++) {
    println("  [" + i + "] " + ports[i]);
  }

  portName = "";
  for (String p : ports) {
    String lower = p.toLowerCase();
    if (lower.indexOf("usbserial") >= 0 || lower.indexOf("slab") >= 0 || lower.indexOf("cp210") >= 0) {
      portName = p;
      break;
    }
  }
  if (portName.length() == 0 && ports.length > 0) {
    portName = ports[0];
  }

  if (portName.length() == 0) {
    status = "no serial ports found";
    return;
  }

  try {
    meter = new Serial(this, portName, baudRate);
    meter.clear();
    status = "connected " + portName + " @ " + baudRate + "-8-N-1";
  } catch (Exception e) {
    status = "serial open failed: " + e.getMessage();
    println(status);
  }
}

//------------------------------------------
void readSerial() {
  if (meter == null) {
    return;
  }

  while (meter.available() > 0) {
    int b = meter.read() & 0xff;
    recordRawByte(b);
    feedPacketByte(b);
    consumeTextByte(rawLine, b);
    consumeTextByte(strippedLine, b & 0x7f);
  }
}

//------------------------------------------
void feedPacketByte(int b) {
  packetTail[packetTailWrite] = b;
  packetTailWrite = (packetTailWrite + 1) % packetTail.length;
  packetTailCount = min(packetTailCount + 1, packetTail.length);

  if (b != 0x03 || packetTailCount < packetTail.length) {
    return;
  }

  int[] frame = new int[13];
  for (int i = 0; i < frame.length; i++) {
    int idx = (packetTailWrite - frame.length + i + packetTail.length) % packetTail.length;
    frame[i] = packetTail[idx] & 0xff;
  }
  parseBinaryFrame(frame);
}

//------------------------------------------
void parseBinaryFrame(int[] frame) {
  boolean signature =
    frame[1] == 0x01 && frame[2] == 0x01 &&
    frame[4] == 0x00 && frame[5] == 0x00 &&
    frame[8] == 0x01 && frame[9] == 0x01 &&
    frame[12] == 0x03;

  if (!signature) {
    return;
  }

  // Empirical MS6252B mapping from the observed USB UART frames.
  rawHumidity = unsigned16(frame[2], frame[3]);
  rawTemperature = signed16(frame[6], frame[7]);
  rawWind = unsigned16(frame[10], frame[11]);
  lastFrameHex = frameHex(frame);

  humidityPct = rawHumidity / 10.0;
  temperatureC = rawTemperature / 10.0;
  windSpeed = rawWind / 100.0;
  hasSerialValue = true;
  binaryMode = true;
}

//------------------------------------------
int unsigned16(int highByte, int lowByte) {
  return ((highByte & 0xff) << 8) | (lowByte & 0xff);
}

int signed16(int highByte, int lowByte) {
  int v = unsigned16(highByte, lowByte);
  if ((v & 0x8000) != 0) {
    v -= 0x10000;
  }
  return v;
}

String frameHex(int[] frame) {
  String s = "";
  for (int i = 0; i < frame.length; i++) {
    if (i > 0) {
      s += " ";
    }
    s += hex(frame[i] & 0xff, 2);
  }
  return s;
}

//------------------------------------------
void consumeTextByte(StringBuilder line, int b) {
  if (b == '\r' || b == '\n') {
    parseCandidate(line.toString());
    line.setLength(0);
    return;
  }

  if (b >= 32 && b <= 126) {
    line.append((char)b);
    if (line.length() > 80) {
      parseCandidate(line.toString());
      line.setLength(0);
    }
    return;
  }

  if (line.length() > 0) {
    parseCandidate(line.toString());
    line.setLength(0);
  }
}

//------------------------------------------
void parseCandidate(String s) {
  if (binaryMode) {
    return;
  }

  String[] m = match(s, "[-+]?\\d+(\\.\\d+)?");
  if (m == null) {
    return;
  }

  float v = parseFloat(m[0]);
  if (!Float.isNaN(v) && v >= 0 && v <= 100) {
    windSpeed = v;
    hasSerialValue = true;
  }
}

//------------------------------------------
void recordRawByte(int b) {
  rawTail[rawTailWrite] = b;
  rawTailWrite = (rawTailWrite + 1) % rawTail.length;
  rawTailCount = min(rawTailCount + 1, rawTail.length);
}

//------------------------------------------
int valueToY(float v) {
  float clamped = constrain(v, 0, 5);
  return round(map(clamped, 0, 5, height - 40, 30));
}


//------------------------------------------
void drawOverlay(float sourceValue) {
  fill(255, 235);
  noStroke();
  rect(0, 0, width, 124);

  float ty = 20; 
  float dy = 20;
  fill(0);
  text("MS6252B Anemometer serial probe", 12, ty+=dy);
  text(status, 12, ty+=dy);
  text("wind: " + nf(sourceValue, 0, 2) + "m/s", 12, ty+=dy); 
  text("temp: " + nf(temperatureC, 0, 1) + "°C", 12, ty+=dy);
  text("RH:   " + nf(humidityPct, 0, 1) + "%", 12, ty+=dy);
  text("raw:  wind=" + rawWind + " temp=" + rawTemperature + " RH=" + rawHumidity, 12, ty+=dy);
  text("frame:" + lastFrameHex, 12, ty+=dy);
  text("hex:  " + hexTail(false), 12, ty+=dy);

}

String hexTail(boolean stripHighBit) {
  String s = "";
  for (int i = 0; i < rawTailCount; i++) {
    int idx = (rawTailWrite - rawTailCount + i + rawTail.length) % rawTail.length;
    int b = rawTail[idx] & 0xff;
    if (stripHighBit) {
      b &= 0x7f;
    }
    if (s.length() > 0) {
      s += " ";
    }
    s += hex(b, 2);
  }
  return s;
}

String asciiTail(boolean stripHighBit) {
  String s = "";
  for (int i = 0; i < rawTailCount; i++) {
    int idx = (rawTailWrite - rawTailCount + i + rawTail.length) % rawTail.length;
    int b = rawTail[idx] & 0xff;
    if (stripHighBit) {
      b &= 0x7f;
    }
    s += (b >= 32 && b <= 126) ? char(b) : '.';
  }
  return s;
}

void keyPressed() {
  if (key == 'r' || key == 'R') {
    connectSerial();
  }
  if (key == 'm' || key == 'M') {
    mouseFallback = !mouseFallback;
  }
}
