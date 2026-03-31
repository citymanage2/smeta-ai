import math
from typing import Literal
from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/calculator", tags=["calculator"])


class RoomInput(BaseModel):
    # Required
    length: float
    width: float
    height: float

    # Doors
    door_count: int = 0
    door_width: float = 0.9
    door_height: float = 2.1

    # Windows
    window_count: int = 0
    window_width: float = 1.2
    window_height: float = 1.4

    # Openings / extra
    extra_opening_area: float = 0.0

    # Ceiling
    ceiling_type: Literal["flat", "cornice", "slope"] = "flat"
    slope_angle: float = Field(default=30.0, ge=0.0, lt=90.0)
    cornice_width: float = 0.0

    # Floor
    floor_type: Literal["flat", "leveled"] = "flat"
    floor_screed_thickness: float = 0.05

    # Skirting
    skirting_height: float = 0.1

    # Walls
    extra_wall_area: float = 0.0
    tile_height: float = 0.0


class RoomResult(BaseModel):
    perimeter: float
    floor_area: float
    ceiling_area: float
    total_volume: float
    wall_area_gross: float
    wall_area_net: float
    wall_tile_area: float
    door_area: float
    window_area: float
    ceiling_area_gross: float
    cornice_area: float
    floor_screed_volume: float
    skirting_length: float
    skirting_area: float
    paint_area_net: float
    wallpaper_area_net: float


def _r(value: float) -> float:
    return round(value, 3)


@router.post("/room", response_model=RoomResult)
def calculate_room(inp: RoomInput) -> RoomResult:
    perimeter = 2 * (inp.length + inp.width)
    floor_area = inp.length * inp.width
    total_volume = inp.length * inp.width * inp.height

    if inp.ceiling_type == "slope":
        angle_rad = math.radians(inp.slope_angle)
        ceiling_area_gross = floor_area / math.cos(angle_rad)
    else:
        ceiling_area_gross = floor_area

    cornice_area = perimeter * inp.cornice_width
    # ceiling_area exposed (net of cornice strip if cornice type)
    ceiling_area = ceiling_area_gross

    wall_area_gross = perimeter * inp.height + inp.extra_wall_area
    door_area = inp.door_count * inp.door_width * inp.door_height
    window_area = inp.window_count * inp.window_width * inp.window_height
    wall_area_net = max(0.0, wall_area_gross - door_area - window_area - inp.extra_opening_area)

    skirting_length = perimeter - inp.door_count * inp.door_width
    skirting_area = skirting_length * inp.skirting_height

    floor_screed_volume = floor_area * inp.floor_screed_thickness

    if inp.tile_height > 0:
        wall_tile_area = max(
            0.0,
            perimeter * min(inp.tile_height, inp.height) - door_area - window_area,
        )
    else:
        wall_tile_area = 0.0

    paint_area_net = wall_area_net
    wallpaper_area_net = wall_area_net

    return RoomResult(
        perimeter=_r(perimeter),
        floor_area=_r(floor_area),
        ceiling_area=_r(ceiling_area),
        total_volume=_r(total_volume),
        wall_area_gross=_r(wall_area_gross),
        wall_area_net=_r(wall_area_net),
        wall_tile_area=_r(wall_tile_area),
        door_area=_r(door_area),
        window_area=_r(window_area),
        ceiling_area_gross=_r(ceiling_area_gross),
        cornice_area=_r(cornice_area),
        floor_screed_volume=_r(floor_screed_volume),
        skirting_length=_r(skirting_length),
        skirting_area=_r(skirting_area),
        paint_area_net=_r(paint_area_net),
        wallpaper_area_net=_r(wallpaper_area_net),
    )
