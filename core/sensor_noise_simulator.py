"""
MEMS Sensor Noise Simulator — Kinematic RASP Evasion
=====================================================
Implements mathematically accurate sensor noise models to defeat
RASP engines that detect virtualized environments via sensor analysis.

Physical smartphones exhibit inherent sensor noise due to:
- Thermal variations in MEMS components
- Electrical interference (1/f flicker noise)
- Ambient vibration coupling
- Quantization artifacts

A perfectly static [0.0, 0.0, 9.8066] accelerometer reading instantly
flags the device as an emulator. This module generates realistic
stochastic noise profiles using Allan Deviation variance analysis.

Based on: "Assessment of Noise of MEMS IMU Sensors of Different Grades
for GNSS/IMU Navigation" (PMC10975684)
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict
import secrets


@dataclass
class SensorNoiseProfile:
    """
    Noise characteristics for a MEMS sensor.
    
    Based on Allan Deviation analysis of consumer-grade IMUs.
    Values calibrated against BMI160/BMI270 (typical smartphone sensors).
    """
    # Bias instability (low-frequency drift) in sensor units
    bias_instability: float = 0.0
    
    # Angle/Velocity Random Walk (high-frequency white noise)
    random_walk: float = 0.0
    
    # Quantization noise (ADC resolution artifacts)
    quantization: float = 0.0
    
    # Rate random walk (integrated white noise)
    rate_random_walk: float = 0.0
    
    # Temperature sensitivity coefficient
    temp_coefficient: float = 0.0


@dataclass 
class SensorState:
    """Current state of a simulated sensor axis."""
    value: float = 0.0
    bias: float = 0.0
    drift_rate: float = 0.0
    last_update: float = 0.0


class MEMSSensorSimulator:
    """
    Simulates realistic MEMS sensor noise for Android virtualization.
    
    Generates continuous stochastic noise that mimics physical hardware:
    - Accelerometer: 3-axis with gravity bias
    - Gyroscope: 3-axis angular velocity
    - Magnetometer: 3-axis magnetic field
    - Barometer: atmospheric pressure
    
    Noise models based on Overlapped Allan Deviation (OADEV) analysis.
    """

    # Default noise profiles for consumer-grade smartphone sensors
    # Values derived from BMI160/BMI270 datasheets and empirical measurements
    
    ACCEL_PROFILE = SensorNoiseProfile(
        bias_instability=0.004,      # m/s² - typical for smartphone accelerometers
        random_walk=0.008,           # m/s²/√Hz - velocity random walk
        quantization=0.0006,         # m/s² - 16-bit ADC quantization
        rate_random_walk=0.00001,    # m/s²/s/√Hz
        temp_coefficient=0.0002,     # m/s²/°C
    )
    
    GYRO_PROFILE = SensorNoiseProfile(
        bias_instability=0.0005,     # rad/s - typical gyro bias instability
        random_walk=0.0003,          # rad/s/√Hz - angle random walk
        quantization=0.00007,        # rad/s - 16-bit ADC
        rate_random_walk=0.000001,   # rad/s/s/√Hz
        temp_coefficient=0.00003,    # rad/s/°C
    )
    
    MAG_PROFILE = SensorNoiseProfile(
        bias_instability=0.5,        # µT - magnetometer drift
        random_walk=0.2,             # µT/√Hz
        quantization=0.15,           # µT - typical resolution
        rate_random_walk=0.001,
        temp_coefficient=0.01,       # µT/°C
    )
    
    BARO_PROFILE = SensorNoiseProfile(
        bias_instability=0.5,        # Pa - pressure drift
        random_walk=0.3,             # Pa/√Hz
        quantization=0.18,           # Pa - typical resolution ~1.5 Pa
        rate_random_walk=0.0001,
        temp_coefficient=0.1,        # Pa/°C
    )

    # Gravity constant (varies slightly by latitude)
    GRAVITY = 9.80665  # m/s² at sea level, 45° latitude

    def __init__(self, 
                 device_profile: str = "samsung_s24",
                 temperature: float = 25.0):
        """
        Initialize sensor simulator.
        
        Args:
            device_profile: Target device for calibration tuning
            temperature: Ambient temperature in Celsius
        """
        self.device_profile = device_profile
        self.temperature = temperature
        self._start_time = time.time()
        
        # Initialize sensor states for each axis
        self._accel_state = [SensorState() for _ in range(3)]
        self._gyro_state = [SensorState() for _ in range(3)]
        self._mag_state = [SensorState() for _ in range(3)]
        self._baro_state = SensorState()
        
        # Initialize random biases (simulates manufacturing variation)
        self._init_biases()
        
        # Current device orientation (Euler angles in radians)
        self._orientation = [0.0, 0.0, 0.0]  # pitch, roll, yaw
        
        # Pending kinematic events from touch/gesture simulation
        self._kinematic_queue: List[Dict] = []

    def _init_biases(self):
        """Initialize random sensor biases (manufacturing variation)."""
        for state in self._accel_state:
            state.bias = random.gauss(0, self.ACCEL_PROFILE.bias_instability * 2)
            state.drift_rate = random.gauss(0, self.ACCEL_PROFILE.rate_random_walk)
            state.last_update = time.time()
        
        for state in self._gyro_state:
            state.bias = random.gauss(0, self.GYRO_PROFILE.bias_instability * 2)
            state.drift_rate = random.gauss(0, self.GYRO_PROFILE.rate_random_walk)
            state.last_update = time.time()
        
        for state in self._mag_state:
            state.bias = random.gauss(0, self.MAG_PROFILE.bias_instability * 2)
            state.drift_rate = random.gauss(0, self.MAG_PROFILE.rate_random_walk)
            state.last_update = time.time()
        
        self._baro_state.bias = random.gauss(0, self.BARO_PROFILE.bias_instability * 2)
        self._baro_state.drift_rate = random.gauss(0, self.BARO_PROFILE.rate_random_walk)
        self._baro_state.last_update = time.time()

    def _apply_noise(self, 
                     base_value: float, 
                     state: SensorState, 
                     profile: SensorNoiseProfile,
                     dt: float) -> float:
        """
        Apply stochastic noise to a sensor reading.
        
        Implements Allan Deviation noise model:
        1. Bias instability (1/f flicker noise, low-frequency drift)
        2. Random walk (white noise integration)
        3. Quantization noise (ADC artifacts)
        4. Temperature drift
        
        Args:
            base_value: Ideal sensor value
            state: Current sensor state
            profile: Noise profile for this sensor type
            dt: Time delta since last reading
        
        Returns:
            Noisy sensor value
        """
        # Update bias drift (slow random walk)
        state.bias += state.drift_rate * dt
        state.bias += random.gauss(0, profile.bias_instability * math.sqrt(dt))
        
        # Clamp bias to reasonable bounds
        max_bias = profile.bias_instability * 10
        state.bias = max(-max_bias, min(max_bias, state.bias))
        
        # Apply bias
        value = base_value + state.bias
        
        # Add velocity/angle random walk (white noise)
        value += random.gauss(0, profile.random_walk * math.sqrt(dt))
        
        # Add quantization noise
        value += random.uniform(-profile.quantization/2, profile.quantization/2)
        
        # Temperature drift
        temp_delta = self.temperature - 25.0  # Reference temp
        value += temp_delta * profile.temp_coefficient
        
        state.last_update = time.time()
        return value

    def get_accelerometer(self) -> Tuple[float, float, float]:
        """
        Get current accelerometer reading with realistic noise.
        
        At rest, accelerometer measures gravity vector:
        - Device flat: [0, 0, 9.8]
        - Device tilted: gravity projects onto device axes
        
        Returns:
            (x, y, z) acceleration in m/s²
        """
        now = time.time()
        
        # Calculate gravity vector based on device orientation
        pitch, roll, yaw = self._orientation
        
        # Gravity in device frame (rotation from world frame)
        gx = -self.GRAVITY * math.sin(pitch)
        gy = self.GRAVITY * math.sin(roll) * math.cos(pitch)
        gz = self.GRAVITY * math.cos(roll) * math.cos(pitch)
        
        # Check for pending kinematic events (touch gestures cause acceleration)
        accel_event = self._get_kinematic_acceleration()
        if accel_event:
            gx += accel_event[0]
            gy += accel_event[1]
            gz += accel_event[2]
        
        # Apply noise to each axis
        dt = now - self._accel_state[0].last_update
        dt = max(0.001, min(dt, 1.0))  # Clamp to reasonable range
        
        x = self._apply_noise(gx, self._accel_state[0], self.ACCEL_PROFILE, dt)
        y = self._apply_noise(gy, self._accel_state[1], self.ACCEL_PROFILE, dt)
        z = self._apply_noise(gz, self._accel_state[2], self.ACCEL_PROFILE, dt)
        
        return (x, y, z)

    def get_gyroscope(self) -> Tuple[float, float, float]:
        """
        Get current gyroscope reading with realistic noise.
        
        At rest, gyroscope should read near-zero with noise.
        During rotation, measures angular velocity.
        
        Returns:
            (x, y, z) angular velocity in rad/s
        """
        now = time.time()
        
        # Base values (at rest = 0, during rotation = angular velocity)
        base_x, base_y, base_z = 0.0, 0.0, 0.0
        
        # Check for pending kinematic events (gestures cause rotation)
        gyro_event = self._get_kinematic_rotation()
        if gyro_event:
            base_x, base_y, base_z = gyro_event
        
        # Apply noise
        dt = now - self._gyro_state[0].last_update
        dt = max(0.001, min(dt, 1.0))
        
        x = self._apply_noise(base_x, self._gyro_state[0], self.GYRO_PROFILE, dt)
        y = self._apply_noise(base_y, self._gyro_state[1], self.GYRO_PROFILE, dt)
        z = self._apply_noise(base_z, self._gyro_state[2], self.GYRO_PROFILE, dt)
        
        return (x, y, z)

    def get_magnetometer(self) -> Tuple[float, float, float]:
        """
        Get current magnetometer reading with realistic noise.
        
        Measures Earth's magnetic field (~25-65 µT depending on location).
        Vector points toward magnetic north with inclination.
        
        Returns:
            (x, y, z) magnetic field in µT
        """
        now = time.time()
        
        # Earth's magnetic field (approximate for mid-latitudes)
        # Horizontal component ~20 µT, vertical ~40 µT (Northern hemisphere)
        field_strength = 48.0  # µT total
        inclination = math.radians(60)  # Magnetic inclination angle
        declination = math.radians(-10)  # Magnetic declination
        
        # Calculate field vector in world frame
        h_component = field_strength * math.cos(inclination)
        v_component = field_strength * math.sin(inclination)
        
        # Rotate to device frame based on orientation
        pitch, roll, yaw = self._orientation
        device_yaw = yaw + declination
        
        base_x = h_component * math.cos(device_yaw)
        base_y = h_component * math.sin(device_yaw)
        base_z = v_component
        
        # Apply noise
        dt = now - self._mag_state[0].last_update
        dt = max(0.001, min(dt, 1.0))
        
        x = self._apply_noise(base_x, self._mag_state[0], self.MAG_PROFILE, dt)
        y = self._apply_noise(base_y, self._mag_state[1], self.MAG_PROFILE, dt)
        z = self._apply_noise(base_z, self._mag_state[2], self.MAG_PROFILE, dt)
        
        return (x, y, z)

    def get_barometer(self, altitude: float = 0.0) -> float:
        """
        Get current barometer reading with realistic noise.
        
        Pressure decreases with altitude (~12 Pa per meter near sea level).
        
        Args:
            altitude: Altitude in meters above sea level
        
        Returns:
            Atmospheric pressure in hPa (mbar)
        """
        now = time.time()
        
        # Standard atmosphere pressure at sea level
        p0 = 1013.25  # hPa
        
        # Barometric formula (simplified)
        scale_height = 8500  # meters
        pressure = p0 * math.exp(-altitude / scale_height)
        
        # Convert to Pa for noise calculation, then back to hPa
        pressure_pa = pressure * 100
        
        dt = now - self._baro_state.last_update
        dt = max(0.001, min(dt, 1.0))
        
        noisy_pa = self._apply_noise(pressure_pa, self._baro_state, self.BARO_PROFILE, dt)
        
        return noisy_pa / 100  # Return in hPa

    def inject_touch_event(self, 
                           event_type: str,
                           x: int, y: int,
                           duration_ms: int = 100,
                           pressure: float = 0.5):
        """
        Inject a touch event that will cause corresponding sensor perturbations.
        
        When a human taps or swipes, the physical force causes measurable
        acceleration and rotation of the device. This synchronizes touch
        automation with realistic IMU responses.
        
        Args:
            event_type: "tap", "swipe_up", "swipe_down", "swipe_left", "swipe_right"
            x, y: Touch coordinates
            duration_ms: Event duration in milliseconds
            pressure: Touch pressure (0.0 - 1.0)
        """
        now = time.time()
        duration_s = duration_ms / 1000.0
        
        # Calculate expected kinematic response based on event type
        # These values simulate the physical perturbation of a handheld device
        
        if event_type == "tap":
            # Tap causes brief downward then upward acceleration
            self._kinematic_queue.append({
                "type": "accel",
                "start": now,
                "duration": duration_s,
                "profile": "tap",
                "magnitude": 0.3 + pressure * 0.4,  # m/s²
            })
            # Small rotation from off-center taps
            offset_x = (x - 540) / 540  # Normalized offset from center
            offset_y = (y - 1200) / 1200
            self._kinematic_queue.append({
                "type": "gyro",
                "start": now,
                "duration": duration_s,
                "profile": "tap",
                "roll_rate": offset_x * 0.02,  # rad/s
                "pitch_rate": offset_y * 0.02,
            })
            
        elif event_type.startswith("swipe"):
            # Swipes cause directional acceleration and rotation
            direction = event_type.split("_")[1]
            accel_vector = {
                "up": (0, -0.5, 0),
                "down": (0, 0.5, 0),
                "left": (-0.5, 0, 0),
                "right": (0.5, 0, 0),
            }.get(direction, (0, 0, 0))
            
            self._kinematic_queue.append({
                "type": "accel",
                "start": now,
                "duration": duration_s * 2,
                "profile": "swipe",
                "vector": accel_vector,
            })
            
            gyro_vector = {
                "up": (0.05, 0, 0),     # Pitch forward
                "down": (-0.05, 0, 0),  # Pitch back
                "left": (0, 0.03, 0),   # Roll left
                "right": (0, -0.03, 0), # Roll right
            }.get(direction, (0, 0, 0))
            
            self._kinematic_queue.append({
                "type": "gyro",
                "start": now,
                "duration": duration_s * 2,
                "profile": "swipe",
                "vector": gyro_vector,
            })

    def _get_kinematic_acceleration(self) -> Optional[Tuple[float, float, float]]:
        """Get current acceleration perturbation from queued events."""
        now = time.time()
        total_accel = [0.0, 0.0, 0.0]
        
        # Process and clean up expired events
        active_events = []
        for event in self._kinematic_queue:
            if event["type"] != "accel":
                active_events.append(event)
                continue
                
            elapsed = now - event["start"]
            if elapsed > event["duration"]:
                continue
            
            active_events.append(event)
            
            # Calculate acceleration based on event profile
            t = elapsed / event["duration"]  # Normalized time [0, 1]
            
            if event["profile"] == "tap":
                # Tap: impulse response (quick spike then decay)
                magnitude = event["magnitude"]
                envelope = math.sin(math.pi * t) * math.exp(-t * 2)
                total_accel[2] -= magnitude * envelope  # Downward tap
                
            elif event["profile"] == "swipe":
                # Swipe: sustained acceleration in direction
                vector = event.get("vector", (0, 0, 0))
                envelope = math.sin(math.pi * t)  # Smooth rise/fall
                for i in range(3):
                    total_accel[i] += vector[i] * envelope
        
        self._kinematic_queue = active_events
        
        if any(a != 0 for a in total_accel):
            return tuple(total_accel)
        return None

    def _get_kinematic_rotation(self) -> Optional[Tuple[float, float, float]]:
        """Get current angular velocity from queued events."""
        now = time.time()
        total_gyro = [0.0, 0.0, 0.0]
        
        active_events = []
        for event in self._kinematic_queue:
            if event["type"] != "gyro":
                active_events.append(event)
                continue
                
            elapsed = now - event["start"]
            if elapsed > event["duration"]:
                continue
            
            active_events.append(event)
            t = elapsed / event["duration"]
            
            if event["profile"] == "tap":
                envelope = math.sin(math.pi * t) * math.exp(-t * 3)
                total_gyro[0] += event.get("pitch_rate", 0) * envelope
                total_gyro[1] += event.get("roll_rate", 0) * envelope
                
            elif event["profile"] == "swipe":
                vector = event.get("vector", (0, 0, 0))
                envelope = math.sin(math.pi * t)
                for i in range(3):
                    total_gyro[i] += vector[i] * envelope
        
        # Don't update kinematic_queue here, done in _get_kinematic_acceleration
        
        if any(g != 0 for g in total_gyro):
            return tuple(total_gyro)
        return None

    def set_orientation(self, pitch: float, roll: float, yaw: float):
        """
        Set device orientation (Euler angles).
        
        Args:
            pitch: Rotation around X axis (radians)
            roll: Rotation around Y axis (radians)
            yaw: Rotation around Z axis (radians)
        """
        self._orientation = [pitch, roll, yaw]

    def get_all_sensors(self) -> Dict[str, any]:
        """
        Get all sensor readings in Android SensorEvent format.
        
        Returns:
            Dictionary with all sensor data
        """
        accel = self.get_accelerometer()
        gyro = self.get_gyroscope()
        mag = self.get_magnetometer()
        baro = self.get_barometer()
        
        return {
            "accelerometer": {
                "type": 1,  # TYPE_ACCELEROMETER
                "values": list(accel),
                "accuracy": 3,  # SENSOR_STATUS_ACCURACY_HIGH
                "timestamp": int(time.time() * 1e9),
            },
            "gyroscope": {
                "type": 4,  # TYPE_GYROSCOPE
                "values": list(gyro),
                "accuracy": 3,
                "timestamp": int(time.time() * 1e9),
            },
            "magnetic_field": {
                "type": 2,  # TYPE_MAGNETIC_FIELD
                "values": list(mag),
                "accuracy": 3,
                "timestamp": int(time.time() * 1e9),
            },
            "pressure": {
                "type": 6,  # TYPE_PRESSURE
                "values": [baro],
                "accuracy": 3,
                "timestamp": int(time.time() * 1e9),
            },
        }


class GPSSensorFusion:
    """
    GPS-IMU Sensor Fusion for location spoofing evasion.
    
    Modern RASP uses Extended Kalman Filters to cross-validate GPS
    coordinates against IMU data. If GPS changes rapidly while IMU
    reports zero motion, spoofing is detected.
    
    This class synchronizes GPS coordinate changes with corresponding
    IMU data to satisfy sensor fusion algorithms.
    """

    def __init__(self, imu_simulator: MEMSSensorSimulator):
        self.imu = imu_simulator
        self._current_position = (0.0, 0.0, 0.0)  # lat, lon, alt
        self._current_velocity = (0.0, 0.0, 0.0)  # m/s in NED frame
        self._trajectory_queue: List[Dict] = []

    def set_position(self, lat: float, lon: float, alt: float = 0.0):
        """Set current GPS position without motion (teleport)."""
        self._current_position = (lat, lon, alt)

    def move_to(self, 
                target_lat: float, 
                target_lon: float,
                target_alt: float = 0.0,
                duration_s: float = 10.0,
                motion_type: str = "walking"):
        """
        Move to target position with synchronized IMU data.
        
        Calculates required velocity and acceleration, then injects
        corresponding IMU events to satisfy EKF sensor fusion.
        
        Args:
            target_lat, target_lon, target_alt: Target coordinates
            duration_s: Time to reach target
            motion_type: "walking", "driving", "stationary"
        """
        now = time.time()
        
        # Calculate distance and bearing
        lat1, lon1, alt1 = self._current_position
        
        # Haversine distance calculation
        R = 6371000  # Earth radius in meters
        dlat = math.radians(target_lat - lat1)
        dlon = math.radians(target_lon - lon1)
        a = (math.sin(dlat/2)**2 + 
             math.cos(math.radians(lat1)) * math.cos(math.radians(target_lat)) * 
             math.sin(dlon/2)**2)
        distance = R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        
        # Bearing calculation
        y = math.sin(dlon) * math.cos(math.radians(target_lat))
        x = (math.cos(math.radians(lat1)) * math.sin(math.radians(target_lat)) -
             math.sin(math.radians(lat1)) * math.cos(math.radians(target_lat)) * math.cos(dlon))
        bearing = math.atan2(y, x)
        
        # Calculate velocity
        velocity = distance / duration_s if duration_s > 0 else 0
        
        # Velocity limits by motion type
        max_velocities = {
            "stationary": 0.5,
            "walking": 2.0,
            "driving": 40.0,
        }
        max_v = max_velocities.get(motion_type, 2.0)
        velocity = min(velocity, max_v)
        
        # Calculate acceleration profile (trapezoidal velocity)
        accel_time = min(duration_s * 0.2, 2.0)  # 20% of duration or 2s max
        peak_accel = velocity / accel_time if accel_time > 0 else 0
        
        # Convert to device frame accelerations
        # Assuming device is held vertically, facing direction of travel
        accel_forward = peak_accel * math.cos(bearing)
        accel_right = peak_accel * math.sin(bearing)
        
        # Queue trajectory with IMU synchronization
        self._trajectory_queue.append({
            "start": now,
            "duration": duration_s,
            "start_pos": self._current_position,
            "end_pos": (target_lat, target_lon, target_alt),
            "velocity": velocity,
            "bearing": bearing,
            "accel_forward": accel_forward,
            "accel_right": accel_right,
            "accel_time": accel_time,
        })
        
        # Update position
        self._current_position = (target_lat, target_lon, target_alt)

    def get_synchronized_position(self) -> Dict:
        """
        Get current position with EKF-coherent IMU data.
        
        Returns GPS coordinates that are mathematically consistent
        with the IMU sensor readings.
        
        Returns:
            Dictionary with GPS and synchronized IMU data
        """
        now = time.time()
        
        # Get base position (interpolate if trajectory active)
        lat, lon, alt = self._current_position
        velocity = 0.0
        bearing = 0.0
        
        for traj in self._trajectory_queue:
            elapsed = now - traj["start"]
            if elapsed < 0 or elapsed > traj["duration"]:
                continue
            
            # Linear interpolation of position
            t = elapsed / traj["duration"]
            lat1, lon1, alt1 = traj["start_pos"]
            lat2, lon2, alt2 = traj["end_pos"]
            
            lat = lat1 + (lat2 - lat1) * t
            lon = lon1 + (lon2 - lon1) * t
            alt = alt1 + (alt2 - alt1) * t
            
            velocity = traj["velocity"]
            bearing = traj["bearing"]
            
            # Inject acceleration events for sensor fusion coherence
            accel_time = traj["accel_time"]
            if elapsed < accel_time:
                # Accelerating phase
                self.imu._kinematic_queue.append({
                    "type": "accel",
                    "start": now,
                    "duration": 0.1,
                    "profile": "swipe",
                    "vector": (
                        traj["accel_forward"] * 0.5,
                        traj["accel_right"] * 0.5,
                        0
                    ),
                })
            elif elapsed > traj["duration"] - accel_time:
                # Decelerating phase
                self.imu._kinematic_queue.append({
                    "type": "accel",
                    "start": now,
                    "duration": 0.1,
                    "profile": "swipe",
                    "vector": (
                        -traj["accel_forward"] * 0.5,
                        -traj["accel_right"] * 0.5,
                        0
                    ),
                })
        
        # Clean up expired trajectories
        self._trajectory_queue = [
            t for t in self._trajectory_queue 
            if now - t["start"] < t["duration"] + 1.0
        ]
        
        return {
            "latitude": lat,
            "longitude": lon,
            "altitude": alt,
            "accuracy": 3.0 + random.gauss(0, 1.5),  # meters
            "speed": velocity + random.gauss(0, 0.2),
            "bearing": math.degrees(bearing) + random.gauss(0, 2),
            "timestamp": int(now * 1000),
            "imu_coherent": True,
        }


# Convenience functions for integration
def create_sensor_stream(device_profile: str = "samsung_s24") -> MEMSSensorSimulator:
    """Create a new sensor simulator instance."""
    return MEMSSensorSimulator(device_profile=device_profile)


def create_gps_fusion(sensor_sim: MEMSSensorSimulator) -> GPSSensorFusion:
    """Create GPS-IMU fusion instance."""
    return GPSSensorFusion(sensor_sim)


if __name__ == "__main__":
    import time
    
    print("MEMS Sensor Noise Simulator - Test Output")
    print("=" * 50)
    
    sim = MEMSSensorSimulator()
    
    print("\nAccelerometer readings (device at rest):")
    print("Expected: noise around [0, 0, 9.8]")
    for i in range(5):
        accel = sim.get_accelerometer()
        print(f"  [{accel[0]:+.4f}, {accel[1]:+.4f}, {accel[2]:+.4f}]")
        time.sleep(0.1)
    
    print("\nGyroscope readings (device at rest):")
    print("Expected: noise around [0, 0, 0]")
    for i in range(5):
        gyro = sim.get_gyroscope()
        print(f"  [{gyro[0]:+.6f}, {gyro[1]:+.6f}, {gyro[2]:+.6f}]")
        time.sleep(0.1)
    
    print("\nSimulating tap event...")
    sim.inject_touch_event("tap", 540, 1200, duration_ms=50)
    print("Accelerometer during tap:")
    for i in range(10):
        accel = sim.get_accelerometer()
        print(f"  [{accel[0]:+.4f}, {accel[1]:+.4f}, {accel[2]:+.4f}]")
        time.sleep(0.02)
    
    print("\n✓ Sensor simulation demonstrates realistic noise patterns")
