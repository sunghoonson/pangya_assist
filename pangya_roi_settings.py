from pangya_models import RoiRect


DEFAULT_ROIS = {
    # 중앙 타겟 아래 빨간색 남은 거리
    # 예: 224y
    "distance": RoiRect(
        name="distance",
        base_x=300,
        base_y=0,
        base_w=1300,
        base_h=500,
    ),

    # 중앙 타겟 오른쪽 흰색 고저차
    # 예: -3.41m, +5.51m
    "height": RoiRect(
        name="height",
        base_x=300,
        base_y=0,
        base_w=1300,
        base_h=500,
    ),

    # 우하단 바람 세기 숫자
    # 예: 5m
    "wind": RoiRect(
        name="wind",
        base_x=1980,
        base_y=1070,
        base_w=65,
        base_h=65,
    ),

    # 우하단 바람 원형 UI 전체
    # 현재 잘 잡히고 있으므로 유지
    "wind_angle": RoiRect(
        name="wind_angle",
        base_x=1880,
        base_y=965,
        base_w=150,
        base_h=150,
    ),
}