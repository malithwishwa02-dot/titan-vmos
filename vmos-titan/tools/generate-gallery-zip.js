#!/usr/bin/env node
/**
 * Module 4: Synthetic Android Gallery Archive Generator
 * Generates a ZIP with DCIM/Camera photos (EXIF-spoofed), 
 * Pictures/Screenshots (PNG), and WhatsApp Images (no EXIF).
 * 
 * Android MediaScanner will index these by EXIF date / filename date,
 * not by file transfer date.
 */

const fs = require('fs');
const path = require('path');
const JSZip = require('jszip');
const { createCanvas } = (() => {
  // Use pure JS canvas generation (no native deps needed)
  return { createCanvas: null };
})();

const OUTDIR = path.join(__dirname, '..', 'generated-data');
fs.mkdirSync(OUTDIR, { recursive: true });

const COUNT = parseInt(process.argv[2]) || 100;

function ri(a, b) { return Math.floor(Math.random() * (b - a + 1)) + a; }

// Generate a random date between 365-730 days ago
function randomPastDate() {
  const now = Date.now();
  const daysAgo = ri(365, 730);
  const hoursOffset = ri(0, 23);
  const minsOffset = ri(0, 59);
  const secsOffset = ri(0, 59);
  const d = new Date(now - daysAgo * 86400000 + hoursOffset * 3600000 + minsOffset * 60000 + secsOffset * 1000);
  return d;
}

function pad(n, len = 2) { return String(n).padStart(len, '0'); }

function dateToFilename(d) {
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
}

function dateToExif(d) {
  return `${d.getFullYear()}:${pad(d.getMonth() + 1)}:${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function dateToScreenshot(d) {
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
}

function dateToWA(d) {
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}`;
}

// ── Generate synthetic JPEG data with EXIF ──────────────────
// Minimal JPEG with EXIF DateTimeOriginal/DateTimeDigitized
function generateJpegWithExif(width, height, date, seed) {
  // Generate a minimal but valid JPEG with random colored blocks
  // We'll create a proper JFIF + EXIF JPEG

  const exifDate = dateToExif(date);
  
  // Build EXIF APP1 segment with DateTimeOriginal and DateTimeDigitized
  const exifData = buildExifSegment(exifDate);
  
  // Generate JPEG image data using a simple approach
  const jpegData = generateMinimalJpeg(width, height, seed);
  
  // Insert EXIF after SOI marker (first 2 bytes FF D8)
  const soi = jpegData.slice(0, 2);
  const rest = jpegData.slice(2);
  
  return Buffer.concat([soi, exifData, rest]);
}

// Build EXIF APP1 segment
function buildExifSegment(dateTimeStr) {
  // EXIF structure: APP1 marker + Exif header + TIFF header + IFD0 + ExifIFD
  const dateBytes = Buffer.from(dateTimeStr + '\0', 'ascii'); // 20 bytes (19 + null)
  
  // We'll build a minimal valid EXIF structure
  // APP1 = FF E1 + length(2) + "Exif\0\0" + TIFF data
  
  const tiffHeader = Buffer.alloc(8);
  tiffHeader.write('II', 0, 'ascii'); // Little-endian
  tiffHeader.writeUInt16LE(42, 2);     // TIFF magic
  tiffHeader.writeUInt32LE(8, 4);      // Offset to IFD0
  
  // IFD0: 1 entry pointing to ExifIFD
  const ifd0EntryCount = Buffer.alloc(2);
  ifd0EntryCount.writeUInt16LE(1, 0);
  
  // IFD0 entry: ExifIFD pointer (tag 0x8769)
  const ifd0Entry = Buffer.alloc(12);
  ifd0Entry.writeUInt16LE(0x8769, 0); // Tag: ExifIFD
  ifd0Entry.writeUInt16LE(4, 2);       // Type: LONG
  ifd0Entry.writeUInt32LE(1, 4);       // Count
  const exifIfdOffset = 8 + 2 + 12 + 4; // tiffHeader + count + entry + nextIFD
  ifd0Entry.writeUInt32LE(exifIfdOffset, 8); // Value: offset to ExifIFD
  
  const nextIfd = Buffer.alloc(4); // Next IFD offset = 0 (none)
  
  // ExifIFD: 2 entries (DateTimeOriginal, DateTimeDigitized)
  const exifEntryCount = Buffer.alloc(2);
  exifEntryCount.writeUInt16LE(2, 0);
  
  const dataOffset = exifIfdOffset + 2 + 24 + 4; // count + 2 entries + nextIFD
  
  // Entry 1: DateTimeOriginal (0x9003)
  const exifEntry1 = Buffer.alloc(12);
  exifEntry1.writeUInt16LE(0x9003, 0); // Tag
  exifEntry1.writeUInt16LE(2, 2);       // Type: ASCII
  exifEntry1.writeUInt32LE(20, 4);      // Count (including null)
  exifEntry1.writeUInt32LE(dataOffset, 8); // Offset to data
  
  // Entry 2: DateTimeDigitized (0x9004)
  const exifEntry2 = Buffer.alloc(12);
  exifEntry2.writeUInt16LE(0x9004, 0);
  exifEntry2.writeUInt16LE(2, 2);
  exifEntry2.writeUInt32LE(20, 4);
  exifEntry2.writeUInt32LE(dataOffset + 20, 8);
  
  const exifNextIfd = Buffer.alloc(4);
  
  // Combine TIFF data
  const tiffData = Buffer.concat([
    tiffHeader, ifd0EntryCount, ifd0Entry, nextIfd,
    exifEntryCount, exifEntry1, exifEntry2, exifNextIfd,
    dateBytes, dateBytes // Two copies: Original + Digitized
  ]);
  
  // APP1 segment
  const exifHeader = Buffer.from('Exif\0\0', 'ascii');
  const app1Data = Buffer.concat([exifHeader, tiffData]);
  const app1Length = app1Data.length + 2; // +2 for length field itself
  
  const app1Marker = Buffer.alloc(4);
  app1Marker.writeUInt8(0xFF, 0);
  app1Marker.writeUInt8(0xE1, 1);
  app1Marker.writeUInt16BE(app1Length, 2);
  
  return Buffer.concat([app1Marker, app1Data]);
}

// Generate minimal valid JPEG image data with random content
function generateMinimalJpeg(width, height, seed) {
  // Create a simple JPEG using raw encoding
  // For efficiency, we'll generate random data that looks like a photo
  // We use a pre-built JPEG structure with randomized DCT data
  
  // Simpler approach: generate random bytes with valid JPEG structure
  const r = (seed * 16807) % 2147483647;
  const g = (r * 16807) % 2147483647;
  const b = (g * 16807) % 2147483647;
  
  // Use a template JPEG approach - create a solid color JPEG
  // Then add random noise bytes to vary the file size (500KB-5MB range)
  const baseColor = [(r % 200) + 30, (g % 200) + 30, (b % 200) + 30];
  
  // Generate using BMP-to-JPEG simulation with raw bytes
  // Actually, let's use a simpler approach: create PPM and convert via a helper
  // Or generate raw JFIF with quantization tables
  
  // Simplest valid approach: Use a pre-made tiny JPEG and pad with JFIF comment
  // to reach realistic file size (500KB - 3MB)
  const targetSize = ri(500, 3000) * 1024; // 500KB to 3MB
  
  // Minimal JPEG: SOI + JFIF APP0 + DQT + SOF0 + DHT + SOS + data + EOI
  // For our purpose, we'll create a valid JPEG structure
  
  // Start with SOI
  const parts = [];
  parts.push(Buffer.from([0xFF, 0xD8])); // SOI
  
  // JFIF APP0
  const jfif = Buffer.alloc(18);
  jfif[0] = 0xFF; jfif[1] = 0xE0; // APP0
  jfif[2] = 0x00; jfif[3] = 0x10; // Length 16
  jfif.write('JFIF\0', 4, 'ascii');
  jfif[9] = 0x01; jfif[10] = 0x01; // Version 1.1
  jfif[11] = 0x00; // Aspect ratio units
  jfif[12] = 0x00; jfif[13] = 0x01; // X density
  jfif[14] = 0x00; jfif[15] = 0x01; // Y density
  jfif[16] = 0x00; jfif[17] = 0x00; // Thumbnail
  parts.push(jfif);
  
  // Add JPEG comment segments to reach target size
  // COM marker = FF FE + length(2) + data
  const maxCommentSize = 65533; // Max segment data size
  let remaining = targetSize - 100; // Reserve for headers/EOI
  
  while (remaining > 0) {
    const chunkSize = Math.min(remaining, maxCommentSize);
    const comHeader = Buffer.alloc(4);
    comHeader[0] = 0xFF; comHeader[1] = 0xFE;
    comHeader.writeUInt16BE(chunkSize + 2, 2);
    
    // Fill with pseudo-random bytes (looks like compressed image data)
    const comData = Buffer.alloc(chunkSize);
    let s = seed + remaining;
    for (let i = 0; i < chunkSize; i++) {
      s = (s * 1103515245 + 12345) & 0x7fffffff;
      comData[i] = s & 0xff;
    }
    
    parts.push(comHeader);
    parts.push(comData);
    remaining -= chunkSize;
  }
  
  // Minimal DQT (quantization table)
  const dqt = Buffer.alloc(69);
  dqt[0] = 0xFF; dqt[1] = 0xDB; // DQT
  dqt[2] = 0x00; dqt[3] = 0x43; // Length
  dqt[4] = 0x00; // Table 0, 8-bit precision
  for (let i = 0; i < 64; i++) dqt[5 + i] = 1; // All-1s quantization
  parts.push(dqt);
  
  // SOF0 (Start of Frame)
  const sof = Buffer.alloc(17);
  sof[0] = 0xFF; sof[1] = 0xC0;
  sof[2] = 0x00; sof[3] = 0x0B; // Length 11
  sof[4] = 0x08; // Precision 8-bit
  sof.writeUInt16BE(1, 5); // Height = 1
  sof.writeUInt16BE(1, 7); // Width = 1
  sof[9] = 0x01; // 1 component
  sof[10] = 0x01; // Component ID
  sof[11] = 0x11; // Sampling factors
  sof[12] = 0x00; // Quant table 0
  parts.push(sof);
  
  // DHT (Huffman table) - minimal
  const dht = Buffer.from([
    0xFF, 0xC4, 0x00, 0x1F, 0x00,
    0x00, 0x01, 0x05, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B
  ]);
  parts.push(dht);
  
  // SOS (Start of Scan)
  const sos = Buffer.from([
    0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01, 0x00, 0x00, 0x3F, 0x00,
    baseColor[0] & 0xFE, 0x00 // Scan data + byte stuff
  ]);
  parts.push(sos);
  
  // EOI
  parts.push(Buffer.from([0xFF, 0xD9]));
  
  return Buffer.concat(parts);
}

// Generate a minimal PNG file with random content
function generatePng(width, height, seed) {
  // Create a minimal valid PNG with random colored pixels
  const targetSize = ri(200, 800) * 1024; // 200KB-800KB for screenshots
  
  // PNG structure: signature + IHDR + IDAT(s) + IEND
  const parts = [];
  
  // PNG signature
  parts.push(Buffer.from([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]));
  
  // IHDR chunk
  const ihdr = Buffer.alloc(25);
  ihdr.writeUInt32BE(13, 0); // Length
  ihdr.write('IHDR', 4, 'ascii');
  ihdr.writeUInt32BE(width || 1080, 8);  // Width
  ihdr.writeUInt32BE(height || 2340, 12); // Height
  ihdr[16] = 8;  // Bit depth
  ihdr[17] = 2;  // Color type (RGB)
  ihdr[18] = 0;  // Compression
  ihdr[19] = 0;  // Filter
  ihdr[20] = 0;  // Interlace
  // CRC of IHDR
  const crc = crc32(ihdr.slice(4, 21));
  ihdr.writeInt32BE(crc, 21);
  parts.push(ihdr);
  
  // Add random data as tEXt chunks to reach target size
  let remaining = targetSize - 100;
  while (remaining > 0) {
    const chunkSize = Math.min(remaining, 32000);
    const textChunk = Buffer.alloc(chunkSize + 12);
    textChunk.writeUInt32BE(chunkSize, 0);
    textChunk.write('tEXt', 4, 'ascii');
    // Random data
    let s = seed + remaining;
    for (let i = 0; i < chunkSize; i++) {
      s = (s * 1103515245 + 12345) & 0x7fffffff;
      textChunk[8 + i] = (s & 0x7f) || 0x20; // Printable ASCII
    }
    const cc = crc32(textChunk.slice(4, 8 + chunkSize));
    textChunk.writeInt32BE(cc, 8 + chunkSize);
    parts.push(textChunk);
    remaining -= chunkSize;
  }
  
  // Minimal IDAT with zlib-compressed empty scanline
  const zlibData = Buffer.from([0x78, 0x01, 0x62, 0x60, 0x60, 0x60, 0x00, 0x00, 0x00, 0x04, 0x00, 0x01]);
  const idat = Buffer.alloc(zlibData.length + 12);
  idat.writeUInt32BE(zlibData.length, 0);
  idat.write('IDAT', 4, 'ascii');
  zlibData.copy(idat, 8);
  const idatCrc = crc32(idat.slice(4, 8 + zlibData.length));
  idat.writeInt32BE(idatCrc, 8 + zlibData.length);
  parts.push(idat);
  
  // IEND chunk
  const iend = Buffer.alloc(12);
  iend.writeUInt32BE(0, 0);
  iend.write('IEND', 4, 'ascii');
  const iendCrc = crc32(iend.slice(4, 8));
  iend.writeInt32BE(iendCrc, 8);
  parts.push(iend);
  
  return Buffer.concat(parts);
}

// CRC32 for PNG chunks
const crcTable = (() => {
  const t = new Int32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) {
      c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
    }
    t[n] = c;
  }
  return t;
})();

function crc32(buf) {
  let c = 0xFFFFFFFF;
  for (let i = 0; i < buf.length; i++) {
    c = crcTable[(c ^ buf[i]) & 0xFF] ^ (c >>> 8);
  }
  return (c ^ 0xFFFFFFFF) | 0;
}

// ── Main generator ──────────────────────────────────────────
async function main() {
  console.log(`=== Gallery Archive Generator (${COUNT} images) ===\n`);
  
  const zip = new JSZip();
  
  const cameraCount = Math.round(COUNT * 0.5);
  const screenshotCount = Math.round(COUNT * 0.3);
  const whatsappCount = COUNT - cameraCount - screenshotCount;
  
  console.log(`Camera photos: ${cameraCount}`);
  console.log(`Screenshots: ${screenshotCount}`);
  console.log(`WhatsApp images: ${whatsappCount}\n`);
  
  let generated = 0;
  
  // A. Camera Photos (JPEG with EXIF)
  console.log('[1/3] Generating camera photos with EXIF...');
  for (let i = 0; i < cameraCount; i++) {
    const date = randomPastDate();
    const filename = `IMG_${dateToFilename(date)}.jpg`;
    const filepath = `DCIM/Camera/${filename}`;
    
    const jpegData = generateJpegWithExif(4000, 3000, date, i * 12345 + 67890);
    zip.file(filepath, jpegData, {
      date: date, // Set ZIP entry date
      compression: 'STORE', // Don't re-compress JPEG
    });
    
    generated++;
    if (generated % 20 === 0) process.stdout.write('.');
  }
  console.log(` ${cameraCount} photos`);
  
  // B. Screenshots (PNG, no EXIF, filename-based dating)
  console.log('[2/3] Generating screenshots...');
  for (let i = 0; i < screenshotCount; i++) {
    const date = randomPastDate();
    const filename = `Screenshot_${dateToScreenshot(date)}.png`;
    const filepath = `Pictures/Screenshots/${filename}`;
    
    const pngData = generatePng(1080, 2340, i * 54321 + 11111);
    zip.file(filepath, pngData, {
      date: date,
      compression: 'STORE',
    });
    
    generated++;
    if (generated % 20 === 0) process.stdout.write('.');
  }
  console.log(` ${screenshotCount} screenshots`);
  
  // C. WhatsApp Images (JPEG, NO EXIF, filename-based dating)
  console.log('[3/3] Generating WhatsApp images...');
  for (let i = 0; i < whatsappCount; i++) {
    const date = randomPastDate();
    const waNum = ri(1000, 9999);
    const filename = `IMG-${dateToWA(date)}-WA${String(waNum).padStart(4, '0')}.jpg`;
    const filepath = `WhatsApp/Media/WhatsApp Images/${filename}`;
    
    // WhatsApp strips EXIF, so generate plain JPEG without EXIF
    const jpegData = generateMinimalJpeg(1280, 960, i * 99999 + 33333);
    zip.file(filepath, jpegData, {
      date: date,
      compression: 'STORE',
    });
    
    generated++;
    if (generated % 20 === 0) process.stdout.write('.');
  }
  console.log(` ${whatsappCount} images`);
  
  // Generate ZIP
  console.log('\nCompressing ZIP archive...');
  const zipBuffer = await zip.generateAsync({
    type: 'nodebuffer',
    compression: 'DEFLATE',
    compressionOptions: { level: 1 }, // Fast compression
    streamFiles: true,
  });
  
  const zipPath = path.join(OUTDIR, 'Android_Media_Archive.zip');
  fs.writeFileSync(zipPath, zipBuffer);
  
  const sizeMB = (zipBuffer.length / (1024 * 1024)).toFixed(1);
  console.log(`\n=== Done ===`);
  console.log(`Archive: ${zipPath} (${sizeMB} MB)`);
  console.log(`Contents: ${generated} files`);
  console.log(`  DCIM/Camera/: ${cameraCount} JPEG (EXIF-spoofed)`);
  console.log(`  Pictures/Screenshots/: ${screenshotCount} PNG`);
  console.log(`  WhatsApp/Media/WhatsApp Images/: ${whatsappCount} JPEG (no EXIF)`);
}

main().catch(e => { console.error(e); process.exit(1); });
