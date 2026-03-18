import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

import get_story_pjsk as pjsk


def get_chara2d_unitAbbr_name_isVS(
    reader: pjsk.Story_reader, chara2dId: int
) -> tuple[str, str, bool]:
    chara2d = reader.character2ds[reader.character2ds_lookup.find_index(chara2dId)]
    if chara2d['characterType'] != 'game_character':
        return '', '', False
    actual_unit = chara2d['unit']
    chara_id = chara2d['characterId']
    chara_unit, name = reader.get_chara_unitAbbr_name(chara_id)
    if chara_unit != 'VS':
        return chara_unit, name, False
    else:
        return pjsk.Constant.unit_code_abbr[actual_unit], name, True
