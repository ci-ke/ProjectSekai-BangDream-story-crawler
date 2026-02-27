from typing import Any

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


def get_event_type(actionSets: list[dict[str, Any]]) -> dict[int, str]:
    ret = {}

    ret[1] = 'band'
    ret[5] = 'idol'
    ret[6] = 'street'
    ret[9] = 'shuffle'

    for action in actionSets:
        releaseConditionId = str(action['releaseConditionId'])
        is_event = (
            ('scenarioId' in action)
            and (
                'areatalk_ev' in action['scenarioId']
                or 'areatalk_wl' in action['scenarioId']
            )
            and (len(releaseConditionId) == 6)
            and (releaseConditionId[0] == '1')
        )
        if is_event:
            event_id = int(releaseConditionId[1:4]) + 1
            scenarioId: str = action['scenarioId']
            event_type = scenarioId.split('_')[2]
            is_wl = scenarioId.split('_')[1] == 'wl'
            if event_id not in ret:
                if is_wl:
                    ret[event_id] = event_type + '_' + 'wl'
                else:
                    ret[event_id] = event_type
    return ret
