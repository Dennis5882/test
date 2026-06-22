# Clause 1.1 適用範圍
# 定義建築物類型分類
class BuildingType:
    ENCLOSED = "enclosed"
    PARTIALLY_ENCLOSED = "partially_enclosed"
    OPEN = "open"

# Clause 1.3 專有名詞定義
# 基本設計風速、用途係數等參數
class WindLoadParameters:
    def __init__(self, basic_wind_speed, importance_factor, effective_area, characteristic_area):
        self.basic_wind_speed = basic_wind_speed  # 基本設計風速 (m/s)
        self.importance_factor = importance_factor  # 用途係數
        self.effective_area = effective_area  # 有效受風面積 (m²)
        self.characteristic_area = characteristic_area  # 特徵面積 (m²)

# 判斷建築物類型
class BuildingClassifier:
    @staticmethod
    def classify(opening_ratio):
        # 根據開口比例判斷，此處為簡化邏輯
        if opening_ratio < 0.05:
            return BuildingType.ENCLOSED
        elif opening_ratio < 0.3:
            return BuildingType.PARTIALLY_ENCLOSED
        else:
            return BuildingType.OPEN
