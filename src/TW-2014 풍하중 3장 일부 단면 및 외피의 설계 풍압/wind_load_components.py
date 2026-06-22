# TW-2014 風荷重 3章 局部構材及外部被覆物設計風壓
# 參考條款: 3.1~3.4

import math

def design_wind_pressure(building_type: str, height: float, roof_height: float,
                         q_h: float, q_z: float, qp: float, qi: float,
                         GCp: float, GCpi: float, G: float, Cpn: float) -> float:
    """
    計算設計風壓 p (kN/m^2)

    Parameters:
    - building_type: 'enclosed_or_partially_enclosed' (封閉式或部分封閉式)
                     'open_sloped_roof' (開放式斜屋頂)
                     'parapet' (女兒牆)
    - height: 建築物高度 (m)
    - roof_height: 屋頂平均高度 (m)
    - q_h: 屋頂平均高度處之風速壓 (kN/m^2)
    - q_z: 高度z處之風速壓 (kN/m^2)
    - qp: 女兒牆頂部之風速壓 (kN/m^2)
    - qi: 內風壓對應之風速壓 (kN/m^2)
    - GCp: 外風壓係數 (含陣風效應)
    - GCpi: 內風壓係數 (含陣風效應)
    - G: 陣風效應因子
    - Cpn: 淨風壓係數

    Returns:
    - p: 設計風壓 (kN/m^2)
    """
    if building_type == 'enclosed_or_partially_enclosed':
        if height <= 18.0:
            # 公式(3.1): p = q(h)[(GCp) - (GCpi)]
            p = q_h * (GCp - GCpi)
        else:
            # 公式(3.2): p = q(GCp) - qi(GCpi)
            # 注意: 迎風面用q_z, 其他面用q_h, 此處簡化為使用q_z
            p = q_z * GCp - qi * GCpi
    elif building_type == 'open_sloped_roof':
        # 公式(3.4): p = q(h) G Cpn
        p = q_h * G * Cpn
    elif building_type == 'parapet':
        # 公式(3.3): p = qp[(GCp) - (GCpi)]
        p = qp * (GCp - GCpi)
    else:
        raise ValueError("Invalid building_type")
    return p

# 範例使用
if __name__ == "__main__":
    # 封閉式建築物高度15m
    p1 = design_wind_pressure('enclosed_or_partially_enclosed', 15.0, 15.0,
                              1.2, 1.2, 0.0, 0.0, 0.8, 0.18, 1.0, 0.0)
    print(f"p1 = {p1:.3f} kN/m^2")

    # 開放式斜屋頂
    p2 = design_wind_pressure('open_sloped_roof', 10.0, 10.0,
                              1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.85, 0.5)
    print(f"p2 = {p2:.3f} kN/m^2")

    # 女兒牆
    p3 = design_wind_pressure('parapet', 20.0, 20.0,
                              1.5, 1.5, 1.8, 0.0, 1.2, 0.18, 1.0, 0.0)
    print(f"p3 = {p3:.3f} kN/m^2")
