import math

# Constants
RHO = 1.25  # Air density (kg/m^3) at 25°C, 1 atm

# Terrain categories: A (open), B (suburban), C (urban)
TERRAIN_PARAMS = {
    'A': {'alpha': 0.12, 'zg': 300, 'b': 1.0},
    'B': {'alpha': 0.16, 'zg': 400, 'b': 0.85},
    'C': {'alpha': 0.22, 'zg': 500, 'b': 0.67}
}

def wind_speed_profile(V10, z, terrain='B'):
    """
    Calculate wind speed at height z using power law (Eq. 2.5).
    V10: basic design wind speed at 10m (m/s)
    z: height (m)
    terrain: 'A', 'B', or 'C'
    """
    alpha = TERRAIN_PARAMS[terrain]['alpha']
    return V10 * (z / 10.0) ** alpha

def exposure_coefficient(z, terrain='B'):
    """
    Calculate exposure coefficient K(z) (Eq. 2.7).
    """
    params = TERRAIN_PARAMS[terrain]
    alpha = params['alpha']
    zg = params['zg']
    if z > 5:
        return 2.774 * (z / zg) ** (2 * alpha)
    else:
        return 2.774 * (5.0 / zg) ** (2 * alpha)

def topographic_factor(K1, K2, K3):
    """
    Calculate topographic factor Kzt (Eq. 2.8).
    K1, K2, K3: factors depending on topography
    """
    return (1 + K1 * K2 * K3) ** 2

def velocity_pressure(z, V10, I, Kzt=1.0, terrain='B'):
    """
    Calculate velocity pressure q(z) (Eq. 2.6).
    z: height (m)
    V10: basic wind speed at 10m (m/s)
    I: importance factor
    Kzt: topographic factor (default 1.0)
    terrain: 'A', 'B', or 'C'
    """
    Kz = exposure_coefficient(z, terrain)
    return 0.06 * Kz * Kzt * (I * V10) ** 2

def gust_factor_general():
    """
    Gust response factor for general buildings (fn > 1 Hz).
    Returns 1.88 as per clause 2.7.
    """
    return 1.88

def gust_factor_flexible(z, V10, I, fn, beta, B, L, h, terrain='B', Kzt=1.0):
    """
    Calculate gust response factor G for flexible buildings (fn <= 1 Hz) using Eq. 2.13.
    z: reference height (m)
    V10: basic wind speed at 10m (m/s)
    I: importance factor
    fn: natural frequency (Hz)
    beta: damping ratio
    B, L, h: building dimensions (m)
    terrain: 'A', 'B', or 'C'
    Kzt: topographic factor
    """
    # Background response Q (simplified, typically from code tables)
    # For demonstration, assume Q = 0.85
    Q = 0.85
    
    # Turbulence intensity Iz
    # Simplified: Iz = 0.2 for open terrain, adjust as needed
    Iz = 0.2
    
    # Peak factors
    gQ = 3.4
    gV = 3.4
    
    # Resonant response factor R (simplified)
    # Using Eq. 2.15-2.19
    Vz = wind_speed_profile(V10, z, terrain)
    Lz = 100.0  # Integral length scale (m), simplified
    N1 = fn * Lz / Vz  # Eq. 2.17
    Rn = 7.47 * N1 / (1 + 10.3 * N1) ** (5.0/3.0)  # Eq. 2.16
    # Simplified Rh, RB, RL (typically from empirical formulas)
    Rh = 0.5
    RB = 0.5
    RL = 0.5
    R = math.sqrt((1.0/beta) * Rn * Rh * RB * (0.53 + 0.47 * RL))  # Eq. 2.15
    
    gR = math.sqrt(2 * math.log(3600 * fn)) + 0.577 / math.sqrt(2 * math.log(3600 * fn))  # Eq. 2.14
    
    G = 1.927 * (1 + 1.7 * Iz * math.sqrt(gQ**2 * Q**2 + gR**2 * R**2)) / (1 + 1.7 * gV * Iz)  # Eq. 2.13
    return G

def design_wind_pressure(q, G, Cp, qi, GCpi):
    """
    Calculate design wind pressure for enclosed/partially enclosed buildings (Eq. 2.1).
    q: velocity pressure at height (kPa)
    G: gust factor
    Cp: external pressure coefficient
    qi: internal velocity pressure (kPa)
    GCpi: internal pressure coefficient
    """
    return q * G * Cp - qi * GCpi

def design_wind_force(q, G, Cf, Ac):
    """
    Calculate design wind force for MWFRS (Eq. 2.4).
    q: velocity pressure at height (kPa)
    G: gust factor
    Cf: force coefficient
    Ac: projected area (m^2)
    """
    return q * G * Cf * Ac

def low_rise_along_wind_force(V10, I, Kzt, lam, Az, h, terrain='B'):
    """
    Simplified along-wind force for low-rise buildings (Eq. 2.25).
    V10: basic wind speed (m/s)
    I: importance factor
    Kzt: topographic factor
    lam: factor (typically 1.0)
    Az: area (m^2)
    h: building height (m)
    terrain: 'A', 'B', or 'C'
    """
    return 1.49 * I * V10 * Kzt * lam**2 * Az

def low_rise_across_wind_force(SDz, L, B):
    """
    Simplified across-wind force for low-rise buildings (Eq. 2.29).
    SDz: along-wind force
    L: building length (m)
    B: building width (m)
    """
    return (0.6 + 0.05 * L / B) * SDz

def low_rise_torsional_moment(SDz_star, B):
    """
    Simplified torsional moment for low-rise buildings (Eq. 2.30).
    SDz_star: along-wind force at reference height
    B: building width (m)
    """
    return 0.21 * B * SDz_star
