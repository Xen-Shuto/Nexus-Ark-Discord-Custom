"""Validate the room that owns the displayed external-settings form.

The owner must travel with browser form values (hidden Textbox), rather than a
server-side State that could already have advanced when a queued save executes.
"""


def settings_form_is_current(room_name, loaded_room, is_switching_room=False):
    return (
        not is_switching_room
        and isinstance(room_name, str)
        and bool(room_name)
        and room_name == loaded_room
    )


FORM_NOT_CURRENT_MESSAGE = (
    "ルーム切替中、または現在のルームの設定が未読み込みのため、操作を中止しました。"
    "切替完了後に「設定を読み込む」を押してから操作してください。"
)
