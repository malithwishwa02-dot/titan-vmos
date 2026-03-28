/**
 * Shared validation & sanitization for VMOS Titan
 * Used by both main process (require) and referenced as patterns in renderer.
 * Zero external dependencies.
 */

'use strict';

// ─── Format Validators ────────────────────────────────────────────────

/** RFC 5322 simplified email: local@domain with basic structure check, max 254 chars */
function isValidEmail(v) {
  if (!v || typeof v !== 'string' || v.length > 254) return false;
  return /^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$/.test(v);
}

/** E.164 phone: + followed by 7-15 digits */
function isValidPhone(v) {
  if (!v || typeof v !== 'string') return false;
  return /^\+[1-9]\d{6,14}$/.test(v);
}

/** Credit card: digit-only after strip, 13-19 length, passes Luhn */
function isValidCC(v) {
  if (!v || typeof v !== 'string') return false;
  const digits = v.replace(/[\s-]/g, '');
  if (!/^\d{13,19}$/.test(digits)) return false;
  // Luhn check
  let sum = 0;
  let alt = false;
  for (let i = digits.length - 1; i >= 0; i--) {
    let n = parseInt(digits[i], 10);
    if (alt) { n *= 2; if (n > 9) n -= 9; }
    sum += n;
    alt = !alt;
  }
  return sum % 10 === 0;
}

/** Expiry: MM/YYYY format, month 01-12, not expired */
function isValidExpiry(v) {
  if (!v || typeof v !== 'string') return false;
  const m = v.match(/^(0[1-9]|1[0-2])\/(\d{4})$/);
  if (!m) return false;
  const month = parseInt(m[1], 10);
  const year = parseInt(m[2], 10);
  const now = new Date();
  const curYear = now.getFullYear();
  const curMonth = now.getMonth() + 1;
  if (year < curYear) return false;
  if (year === curYear && month < curMonth) return false;
  if (year > curYear + 20) return false;
  return true;
}

/** CVV: 3-4 digits only */
function isValidCVV(v) {
  if (!v || typeof v !== 'string') return false;
  return /^\d{3,4}$/.test(v);
}

/** Date: MM/DD/YYYY format, parseable, reasonable range */
function isValidDate(v) {
  if (!v || typeof v !== 'string') return false;
  const m = v.match(/^(0[1-9]|1[0-2])\/(0[1-9]|[12]\d|3[01])\/(\d{4})$/);
  if (!m) return false;
  const d = new Date(parseInt(m[3], 10), parseInt(m[1], 10) - 1, parseInt(m[2], 10));
  if (isNaN(d.getTime())) return false;
  const year = d.getFullYear();
  return year >= 1920 && year <= new Date().getFullYear();
}

/** ZIP: US 5-digit or 5+4 format */
function isValidZip(v) {
  if (!v || typeof v !== 'string') return false;
  return /^\d{5}(-\d{4})?$/.test(v);
}

/** US state: 2-letter code */
const US_STATES = new Set([
  'AL','AK','AZ','AR','CA','CO','CT','DE','FL','GA','HI','ID','IL','IN','IA',
  'KS','KY','LA','ME','MD','MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ',
  'NM','NY','NC','ND','OH','OK','OR','PA','RI','SC','SD','TN','TX','UT','VT',
  'VA','WA','WV','WI','WY','DC',
]);
function isValidState(v) {
  if (!v || typeof v !== 'string') return false;
  return US_STATES.has(v.toUpperCase());
}

/** Supported country codes */
const VALID_COUNTRIES = new Set(['US', 'GB', 'DE', 'FR', 'CA', 'AU']);
function isValidCountry(v) {
  if (!v || typeof v !== 'string') return false;
  return VALID_COUNTRIES.has(v.toUpperCase());
}

/** Age days: integer 7-900 */
function isValidAgeDays(v) {
  const n = typeof v === 'string' ? parseInt(v, 10) : v;
  return Number.isInteger(n) && n >= 7 && n <= 900;
}

/** padCode: alphanumeric + hyphens + underscores, 1-64 chars */
function isValidPadCode(v) {
  if (!v || typeof v !== 'string') return false;
  return /^[a-zA-Z0-9_-]{1,64}$/.test(v);
}

// ─── Proxy URL validation ─────────────────────────────────────────────

const PRIVATE_IP_RANGES = [
  /^127\./,                                       // 127.0.0.0/8
  /^10\./,                                        // 10.0.0.0/8
  /^172\.(1[6-9]|2\d|3[01])\./,                   // 172.16.0.0/12
  /^192\.168\./,                                   // 192.168.0.0/16
  /^169\.254\./,                                   // link-local
  /^0\./,                                          // 0.0.0.0/8
  /^fc/i, /^fd/i, /^fe80/i,                       // IPv6 private
];

function isValidProxyUrl(v) {
  if (!v || typeof v !== 'string' || v.length > 500) return false;
  let u;
  try { u = new URL(v); } catch { return false; }
  // Only allow http, https, socks5
  const proto = u.protocol.replace(':', '').toLowerCase();
  if (!['http', 'https', 'socks5', 'socks5h', 'socks4'].includes(proto)) return false;
  // Reject private/localhost IPs
  const host = u.hostname.toLowerCase();
  if (host === 'localhost' || host === '::1') return false;
  for (const re of PRIVATE_IP_RANGES) {
    if (re.test(host)) return false;
  }
  // Port bounds
  const port = parseInt(u.port, 10);
  if (u.port && (isNaN(port) || port < 1 || port > 65535)) return false;
  return true;
}

// ─── Sanitization ─────────────────────────────────────────────────────

/** Strict shell sanitization: only allow safe characters */
function sanitizeShell(v, maxLen) {
  if (!v || typeof v !== 'string') return '';
  return v.replace(/[^a-zA-Z0-9@._\-+ ]/g, '').slice(0, maxLen || 500);
}

/** SQL value sanitization: remove injection metacharacters */
function sanitizeSQL(v, maxLen) {
  if (!v || typeof v !== 'string') return '';
  return v
    .replace(/'/g, '')
    .replace(/"/g, '')
    .replace(/;/g, '')
    .replace(/`/g, '')
    .replace(/\\/g, '')
    .replace(/\$/g, '')
    .replace(/\|/g, '')
    .replace(/&/g, '')
    .replace(/\n/g, '')
    .replace(/\r/g, '')
    .replace(/--/g, '')
    .replace(/\/\*/g, '')
    .replace(/\*\//g, '')
    .slice(0, maxLen || 1000);
}

/** Generic text sanitization: remove shell + SQL dangerous chars */
function sanitizeText(v, maxLen) {
  if (!v || typeof v !== 'string') return '';
  return v
    .replace(/['"`;`\\$|&\n\r><(){}[\]]/g, '')
    .replace(/--/g, '')
    .replace(/\/\*/g, '')
    .replace(/\*\//g, '')
    .trim()
    .slice(0, maxLen || 500);
}

// ─── Schema Validation ───────────────────────────────────────────────

/**
 * Validate genesis job input data.
 * Returns { valid: true } or { valid: false, errors: { field: message, ... } }
 */
function validateGenesisInput(data) {
  const errors = {};

  // Required: device_id
  if (!data.device_id || typeof data.device_id !== 'string' || !isValidPadCode(data.device_id)) {
    errors.device_id = 'Valid device ID is required';
  }

  // Name: optional but if present, 2-100 chars
  if (data.name && (typeof data.name !== 'string' || data.name.length < 2 || data.name.length > 100)) {
    errors.name = 'Name must be 2-100 characters';
  }

  // Email: optional but if present, must be valid
  if (data.email && !isValidEmail(data.email)) {
    errors.email = 'Invalid email format';
  }

  // Phone: optional but if present, must be E.164
  if (data.phone && !isValidPhone(data.phone)) {
    errors.phone = 'Phone must be E.164 format (e.g. +12025551234)';
  }

  // DOB: optional but if present, must be valid date
  if (data.dob && !isValidDate(data.dob)) {
    errors.dob = 'Date must be MM/DD/YYYY format';
  }

  // Country: required, must be in allowed set
  if (data.country && !isValidCountry(data.country)) {
    errors.country = 'Country must be one of: US, GB, DE, FR, CA, AU';
  }

  // Age days: must be 7-900
  if (data.age_days !== undefined && data.age_days !== null && data.age_days !== '') {
    if (!isValidAgeDays(data.age_days)) {
      errors.age_days = 'Age days must be 7-900';
    }
  }

  // Credit card fields: all-or-nothing validation
  const hasCC = data.cc_number && data.cc_number.replace(/[\s-]/g, '').length > 0;
  if (hasCC) {
    if (!isValidCC(data.cc_number)) {
      errors.cc_number = 'Invalid card number (must pass Luhn check, 13-19 digits)';
    }
    if (data.cc_exp && !isValidExpiry(data.cc_exp)) {
      errors.cc_exp = 'Expiry must be MM/YYYY format, not expired';
    }
    if (data.cc_cvv && !isValidCVV(data.cc_cvv)) {
      errors.cc_cvv = 'CVV must be 3-4 digits';
    }
  }

  // Google email: optional but must be valid email if present
  if (data.google_email && !isValidEmail(data.google_email)) {
    errors.google_email = 'Invalid Gmail address';
  }

  // Google password: if provided, 1-128 chars
  if (data.google_password && (typeof data.google_password !== 'string' || data.google_password.length > 128)) {
    errors.google_password = 'Password must be 1-128 characters';
  }

  // Address fields: length limits
  if (data.street && (typeof data.street !== 'string' || data.street.length > 200)) {
    errors.street = 'Street must be under 200 characters';
  }
  if (data.city && (typeof data.city !== 'string' || data.city.length > 100)) {
    errors.city = 'City must be under 100 characters';
  }
  if (data.state && typeof data.state === 'string' && data.state.length > 0) {
    if (data.state.length > 50) {
      errors.state = 'State must be under 50 characters';
    }
  }
  if (data.zip && typeof data.zip === 'string' && data.zip.length > 0) {
    if (data.zip.length > 20) {
      errors.zip = 'ZIP must be under 20 characters';
    }
  }

  // Proxy URL: if present, validate
  if (data.proxy_url && !isValidProxyUrl(data.proxy_url)) {
    errors.proxy_url = 'Proxy must be http/https/socks5 with non-private IP';
  }

  return Object.keys(errors).length === 0
    ? { valid: true }
    : { valid: false, errors };
}

/** Whitelist of allowed property keys for updatePadProperties */
const ALLOWED_PROPERTY_KEYS = new Set([
  'brand', 'model', 'fingerprint', 'batteryLevel', 'batteryStatus',
  'androidVersion', 'resolution', 'deviceName', 'language', 'timezone',
]);

function filterProperties(props) {
  const filtered = {};
  for (const [k, v] of Object.entries(props)) {
    if (ALLOWED_PROPERTY_KEYS.has(k)) {
      filtered[k] = typeof v === 'string' ? v.slice(0, 500) : v;
    }
  }
  return filtered;
}

// ─── Exports ──────────────────────────────────────────────────────────
module.exports = {
  isValidEmail,
  isValidPhone,
  isValidCC,
  isValidExpiry,
  isValidCVV,
  isValidDate,
  isValidZip,
  isValidState,
  isValidCountry,
  isValidAgeDays,
  isValidPadCode,
  isValidProxyUrl,
  sanitizeShell,
  sanitizeSQL,
  sanitizeText,
  validateGenesisInput,
  filterProperties,
  VALID_COUNTRIES,
  US_STATES,
  ALLOWED_PROPERTY_KEYS,
};
