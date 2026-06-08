import os
import re
import time
import math
import cv2
import numpy as np

try:
    import easyocr
except Exception:
    easyocr = None

from pangya_models import AutoDetectedInput


class PangyaVisionRecognizer:
    def __init__(self, use_easyocr=False, debug_save=True):
        self.use_easyocr = use_easyocr
        self.debug_save = debug_save
        self.reader = None

        if use_easyocr:
            if easyocr is None:
                raise RuntimeError("easyocr가 설치되어 있지 않습니다. pip install easyocr")
            self.reader = easyocr.Reader(["en"], gpu=False)

    def ensure_bgr(self, image):
        if image is None:
            return None

        if len(image.shape) == 2:
            return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)

        if image.shape[2] == 4:
            return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)

        return image

    def save_debug_image(self, image, prefix):
        if not self.debug_save:
            return

        os.makedirs("debug_vision", exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = os.path.join("debug_vision", f"{prefix}_{ts}.png")
        cv2.imwrite(path, image)

    def find_target_line_x(self, image):
        """
        넓은 target ROI 안에서 초록색 세로 타겟 라인을 찾는다.
        이 x좌표를 기준으로 거리/고저차 후보를 좁힌다.
        """
        image = self.ensure_bgr(image)
        b, g, r = cv2.split(image)

        # 밝은 초록색 라인/점 추출
        mask = ((g > 180) & (r < 90) & (b < 170)).astype(np.uint8) * 255

        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)

        best = None

        for i in range(1, num_labels):
            x, y, w, h, area = stats[i]

            # 세로 라인은 높이가 길고 폭이 좁다
            if h >= 80 and w <= 8 and area >= 80:
                if best is None or h > best[3]:
                    best = (x, y, w, h, area, centroids[i])

        if best is None:
            return None

        cx = int(best[5][0])
        return cx

    def crop_around_target_line(self, image, target_x, left=130, right=180, top=40, bottom=230):
        """
        target_x 주변만 다시 잘라서 OCR 후보를 줄인다.
        """
        h, w = image.shape[:2]

        x1 = max(0, target_x - left)
        x2 = min(w, target_x + right)
        y1 = max(0, top)
        y2 = min(h, bottom)

        return image[y1:y2, x1:x2]

    def extract_red_text(self, image):
        """
        남은 비거리 빨간색 텍스트 추출.
        예: 224y
        """
        image = self.ensure_bgr(image)

        target_x = self.find_target_line_x(image)

        if target_x is not None:
            work = self.crop_around_target_line(
                image,
                target_x,
                left=120,
                right=120,
                top=120,
                bottom=360,
            )
        else:
            work = image

        hsv = cv2.cvtColor(work, cv2.COLOR_BGR2HSV)

        # 빨간색은 Hue가 0 근처 또는 180 근처
        lower_red1 = np.array([0, 70, 80])
        upper_red1 = np.array([12, 255, 255])
        lower_red2 = np.array([168, 70, 80])
        upper_red2 = np.array([179, 255, 255])

        mask1 = cv2.inRange(hsv, lower_red1, upper_red1)
        mask2 = cv2.inRange(hsv, lower_red2, upper_red2)
        mask = cv2.bitwise_or(mask1, mask2)

        # 글자 굵게
        kernel = np.ones((2, 2), np.uint8)
        mask = cv2.dilate(mask, kernel, iterations=1)

        # OCR용 흰 글자/검은 배경 이미지 생성
        out = np.zeros_like(mask)
        out[mask > 0] = 255

        out = cv2.resize(out, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)

        self.save_debug_image(out, "distance_red_processed")

        return out

    def find_red_text_bbox(self, image):
        """
        넓은 target ROI 안에서 빨간 거리 텍스트 bbox를 찾는다.
        예: 224y
        """
        image = self.ensure_bgr(image)
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

        lower_red1 = np.array([0, 70, 80])
        upper_red1 = np.array([12, 255, 255])
        lower_red2 = np.array([168, 70, 80])
        upper_red2 = np.array([179, 255, 255])

        mask1 = cv2.inRange(hsv, lower_red1, upper_red1)
        mask2 = cv2.inRange(hsv, lower_red2, upper_red2)
        mask = cv2.bitwise_or(mask1, mask2)

        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)

        boxes = []

        for i in range(1, num_labels):
            x, y, w, h, area = stats[i]

            if area < 10:
                continue

            # 빨간 거리 글자는 너무 작지도, 너무 크지도 않음
            if h < 5 or h > 30:
                continue

            if w < 3 or w > 40:
                continue

            boxes.append((x, y, w, h, area))

        if not boxes:
            return None

        # 서로 가까운 빨간 글자 컴포넌트들을 하나의 bbox로 묶음
        xs = []
        ys = []
        xe = []
        ye = []

        for x, y, w, h, area in boxes:
            xs.append(x)
            ys.append(y)
            xe.append(x + w)
            ye.append(y + h)

        return min(xs), min(ys), max(xe), max(ye)
    
    def extract_white_text(self, image):
        """
        고저차 흰색 텍스트 추출.
        예: -3.41m, +5.51m
        """
        image = self.ensure_bgr(image)

        red_bbox = self.find_red_text_bbox(image)

        if red_bbox is not None:
            rx1, ry1, rx2, ry2 = red_bbox

            h, w = image.shape[:2]

            # 빨간 거리 텍스트 기준:
            # 고저차는 보통 빨간 거리보다 위쪽 + 오른쪽에 있음
            x1 = max(0, rx1 + 10)
            x2 = min(w, rx2 + 160)
            y1 = max(0, ry1 - 65)
            y2 = min(h, ry1 - 5)

            work = image[y1:y2, x1:x2]
        else:
            target_x = self.find_target_line_x(image)

            if target_x is not None:
                work = self.crop_around_target_line(
                    image,
                    target_x,
                    left=20,
                    right=240,
                    top=180,
                    bottom=330,
                )
            else:
                work = image

        hsv = cv2.cvtColor(work, cv2.COLOR_BGR2HSV)

        # 고저차 흰색 글자 추출
        lower_white = np.array([0, 0, 150])
        upper_white = np.array([179, 95, 255])
        mask = cv2.inRange(hsv, lower_white, upper_white)

        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)

        filtered = np.zeros_like(mask)

        for i in range(1, num_labels):
            x, y, cw, ch, area = stats[i]

            if area < 3:
                continue

            # 너무 큰 격자/라인 제거
            if area > 260:
                continue

            if ch > 28:
                continue

            if cw > 55:
                continue

            filtered[labels == i] = 255

        # 고저차는 너무 굵게 만들면 3/8 오인식이 심해짐
        out = cv2.resize(filtered, None, fx=5, fy=5, interpolation=cv2.INTER_NEAREST)

        self.save_debug_image(out, "height_white_processed")

        return out

    def extract_wind_text(self, image):
        """
        우하단 바람 숫자 추출.
        예: 5m
        """
        image = self.ensure_bgr(image)

        # 현재 wind ROI에는 이미 5m이 들어오므로 내부 crop하지 않는다.
        work = image

        hsv = cv2.cvtColor(work, cv2.COLOR_BGR2HSV)

        # 바람 글자: 밝은 하늘색/흰색 계열
        # 검은 그림자는 버리고 밝은 외곽/채움만 사용
        lower_cyan = np.array([80, 20, 120])
        upper_cyan = np.array([110, 255, 255])

        lower_white = np.array([0, 0, 150])
        upper_white = np.array([179, 90, 255])

        mask_cyan = cv2.inRange(hsv, lower_cyan, upper_cyan)
        mask_white = cv2.inRange(hsv, lower_white, upper_white)

        mask = cv2.bitwise_or(mask_cyan, mask_white)

        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)

        filtered = np.zeros_like(mask)

        for i in range(1, num_labels):
            x, y, cw, ch, area = stats[i]

            if area < 4:
                continue

            # 너무 큰 원형 테두리 조각 제거
            if area > 700:
                continue

            if cw > 60:
                continue

            if ch > 45:
                continue

            filtered[labels == i] = 255

        kernel = np.ones((2, 2), np.uint8)
        filtered = cv2.dilate(filtered, kernel, iterations=1)

        out = cv2.resize(filtered, None, fx=5, fy=5, interpolation=cv2.INTER_NEAREST)

        self.save_debug_image(out, "wind_processed")

        return out

    def crop_nonzero_region(self, image, padding=12):
        """
        흑백 전처리 이미지에서 실제 글자가 있는 영역만 잘라낸다.
        """
        if image is None:
            return image

        gray = image
        if len(gray.shape) == 3:
            gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)

        points = cv2.findNonZero(gray)

        if points is None:
            return image

        x, y, w, h = cv2.boundingRect(points)

        ih, iw = gray.shape[:2]

        x1 = max(0, x - padding)
        y1 = max(0, y - padding)
        x2 = min(iw, x + w + padding)
        y2 = min(ih, y + h + padding)

        return gray[y1:y2, x1:x2]

    def crop_left_digit_area(self, image):
        """
        바람값 5m에서 숫자 영역만 남기기 위한 crop.
        m까지 OCR에 넣으면 5를 3으로 오인식하는 경우가 있어 숫자 쪽만 사용한다.
        """
        gray = image

        if len(gray.shape) == 3:
            gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)

        points = cv2.findNonZero(gray)

        if points is None:
            return gray

        x, y, w, h = cv2.boundingRect(points)

        cropped = gray[y:y + h, x:x + w]

        ch, cw = cropped.shape[:2]

        # 5m 중 왼쪽 숫자 5만 남김
        # m은 오른쪽에 있으므로 약 45~55%만 사용
        digit_w = max(1, int(cw * 0.48))
        cropped = cropped[:, :digit_w]

        return cropped
    
    def read_number_from_processed_image(self, processed_image, allow_sign=True, allow_decimal=True, crop=True):
        """
        전처리된 흑백 이미지에서 숫자 읽기.
        easyocr가 꺼져 있으면 None 반환.
        """
        if self.reader is None:
            return None

        img = processed_image

        if crop:
            img = self.crop_nonzero_region(img, padding=14)

        self.save_debug_image(img, "ocr_input")

        allowlist = "0123456789"

        if allow_sign:
            allowlist += "+-"

        if allow_decimal:
            allowlist += "."

        # y/m은 되도록 OCR 대상에서 제외한다.
        # 거리의 y, 바람의 m이 1/3 등으로 오인식되는 문제가 있음.
        results = self.reader.readtext(
            img,
            detail=0,
            allowlist=allowlist,
            paragraph=False,
        )

        if not results:
            return None

        text = "".join(results)
        text = text.strip()

        match = re.search(r"[-+]?\d+(?:\.\d+)?", text)

        if not match:
            return None

        try:
            return float(match.group(0))
        except Exception:
            return None

    def normalize_distance_value(self, value):
        """
        거리 OCR 보정.
        예: 224y를 2241로 읽는 경우 y를 1로 오인식한 것으로 보고 224로 보정.
        """
        if value is None:
            return None

        try:
            value = float(value)
        except Exception:
            return None

        # 팡야 남은 거리는 일반적으로 0~400y 범위로 본다.
        if 0 <= value <= 400:
            return value

        text = str(int(value))

        # 2241 -> 224, 2841 -> 284 같은 케이스 보정
        while len(text) >= 3:
            text = text[:-1]

            try:
                fixed = float(text)
            except Exception:
                continue

            if 0 <= fixed <= 400:
                return fixed

        return value

    def normalize_wind_value(self, value):
        """
        바람 OCR 보정.
        팡야 바람은 일반적으로 0~9 또는 0~10 정도로 제한.
        """
        if value is None:
            return None

        try:
            value = float(value)
        except Exception:
            return None

        if 0 <= value <= 15:
            return value

        text = str(int(value))

        # 51, 5m이 51 등으로 읽힌 경우 앞자리 우선
        for i in range(1, len(text) + 1):
            try:
                fixed = float(text[:i])
            except Exception:
                continue

            if 0 <= fixed <= 15:
                return fixed

        return None

    def normalize_height_value(self, value):
        """
        고저차 OCR 보정.
        너무 비현실적인 값은 버린다.
        """
        if value is None:
            return None

        try:
            value = float(value)
        except Exception:
            return None

        # 일단 넉넉하게 허용
        if -100 <= value <= 100:
            return value

        return None
    
    def recognize_distance(self, image):
        red_mask_img = self.extract_red_text(image)

        value = self.read_number_from_processed_image(
            red_mask_img,
            allow_sign=False,
            allow_decimal=False,
        )

        return self.normalize_distance_value(value)

    def recognize_height(self, image):
        white_mask_img = self.extract_white_text(image)

        # 실제 고저차 글자가 있는 부분만 타이트하게 crop
        height_crop = self.crop_nonzero_region(white_mask_img, padding=16)
        self.save_debug_image(height_crop, "height_crop_only")

        value = self.read_number_from_processed_image(
            height_crop,
            allow_sign=True,
            allow_decimal=True,
            crop=False,
        )

        return self.normalize_height_value(value)

    def recognize_wind(self, image):
        wind_img = self.extract_wind_text(image)

        # 5m 중 숫자 5 영역만 사용
        wind_digit_img = self.crop_left_digit_area(wind_img)
        self.save_debug_image(wind_digit_img, "wind_digit_only")

        value = self.read_number_from_processed_image(
            wind_digit_img,
            allow_sign=False,
            allow_decimal=False,
            crop=True,
        )

        return self.normalize_wind_value(value)

    def recognize_wind_angle(self, image):
        """
        바람 화살표 방향 추정.
        기준:
        - 위쪽 수직 방향 = 0도
        - 오른쪽 = 90도
        - 아래쪽 = 180도
        - 왼쪽 = 270도
        """
        image = self.ensure_bgr(image)

        h, w = image.shape[:2]
        cx = w // 2
        cy = h // 2

        # 원형 UI의 하얀 테두리와 숫자 영역은 제외하고 내부만 사용
        yy, xx = np.ogrid[:h, :w]
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)

        inner_circle = dist < min(w, h) * 0.42

        b, g, r = cv2.split(image)

        # 밝은 청록/파란 화살표만 추출
        # B와 G가 높고 R이 낮은 영역
        mask = (
            (b > 130) &
            (g > 120) &
            (r < 80) &
            inner_circle
        ).astype(np.uint8) * 255

        # 노이즈 제거
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.dilate(mask, kernel, iterations=1)

        self.save_debug_image(mask, "wind_angle_arrow_mask")

        points = cv2.findNonZero(mask)

        if points is None:
            return None

        points = points.reshape(-1, 2)

        # 화살표는 중심에서 한 방향으로 길게 뻗어 있으므로
        # 중심에서 가장 먼 점을 화살표 끝으로 본다.
        best_point = None
        best_dist = 0.0

        for x, y in points:
            dx = float(x - cx)
            dy = float(y - cy)
            d = math.sqrt(dx * dx + dy * dy)

            # 너무 중심부에 가까운 점은 제외
            if d < min(w, h) * 0.12:
                continue

            if d > best_dist:
                best_dist = d
                best_point = (int(x), int(y))

        if best_point is None:
            return None

        tip_x, tip_y = best_point

        dx = tip_x - cx
        dy = tip_y - cy

        # 위쪽 수직 방향을 0도로 하는 각도
        deg = math.degrees(math.atan2(dx, -dy))

        if deg < 0:
            deg += 360.0

        return round(deg, 1)

    def recognize_all(self, distance_img, height_img, wind_img, wind_angle_img):
        detected = AutoDetectedInput()

        detected.distance = self.recognize_distance(distance_img)
        detected.height = self.recognize_height(height_img)
        detected.wind = self.recognize_wind(wind_img)
        detected.degree = self.recognize_wind_angle(wind_angle_img)

        return detected