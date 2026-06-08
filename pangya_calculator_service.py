from pangya_acrisio import calc_shot
from pangya_models import AutoDetectedInput, ShotDisplayResult


DEFAULT_SHOTS = ["DUNK", "TOMAHAWK", "SPIKE", "COBRA"]


class PangyaCalculatorService:
    def __init__(
        self,
        power=31.0,
        auxpart_pwr=0.0,
        card_pwr=4.0,
        mascot_pwr=4.0,
        card_ps_pwr=8.0,
        club="_1W",
        power_shot="NO_POWER_SHOT",
        board_per_pb=0.2121,
        smart_divisor=4.0,
    ):
        self.power = power
        self.auxpart_pwr = auxpart_pwr
        self.card_pwr = card_pwr
        self.mascot_pwr = mascot_pwr
        self.card_ps_pwr = card_ps_pwr
        self.club = club
        self.power_shot = power_shot
        self.board_per_pb = board_per_pb
        self.smart_divisor = smart_divisor

    def calculate_one(self, auto_input: AutoDetectedInput, shot: str) -> ShotDisplayResult:
        if auto_input.distance is None:
            return ShotDisplayResult(
                shot=shot,
                ok=False,
                message="Distance 인식값 없음"
            )

        if auto_input.height is None:
            return ShotDisplayResult(
                shot=shot,
                ok=False,
                message="Height 인식값 없음"
            )

        if auto_input.wind is None:
            return ShotDisplayResult(
                shot=shot,
                ok=False,
                message="Wind 인식값 없음"
            )

        if auto_input.degree is None:
            return ShotDisplayResult(
                shot=shot,
                ok=False,
                message="Degree 인식값 없음"
            )

        try:
            result = calc_shot(
                power=self.power,
                auxpart_pwr=self.auxpart_pwr,
                card_pwr=self.card_pwr,
                mascot_pwr=self.mascot_pwr,
                card_ps_pwr=self.card_ps_pwr,
                club=self.club,
                shot=shot,
                power_shot=self.power_shot,
                distance=auto_input.distance,
                height=auto_input.height,
                wind=auto_input.wind,
                degree=auto_input.degree,
                ground=auto_input.ground,
                spin=auto_input.spin,
                curve=auto_input.curve,
                slope=str(auto_input.slope or 0.0),
                line_ball=0.0,
                line_ball_random=False,
            )

            if not result.ok:
                return ShotDisplayResult(
                    shot=shot,
                    ok=False,
                    message=result.message
                )

            board_cells = abs(result.pb) * self.board_per_pb
            smart_cells = board_cells / self.smart_divisor

            return ShotDisplayResult(
                shot=shot,
                ok=True,
                power_percent=result.power_percent,
                shot_yards=result.shot_yards,
                board_cells=board_cells,
                smart_cells=smart_cells,
                message="ok"
            )

        except Exception as e:
            return ShotDisplayResult(
                shot=shot,
                ok=False,
                message=str(e)
            )

    def calculate_all(self, auto_input: AutoDetectedInput, shots=None):
        if shots is None:
            shots = DEFAULT_SHOTS

        results = {}

        for shot in shots:
            results[shot] = self.calculate_one(auto_input, shot)

        return results