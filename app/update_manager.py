import logging
from version_manager import VersionManager

logger = logging.getLogger(__name__)


class UpdateManager:
    """Custom build: upstream updates are permanently disabled; restart is retained."""

    APP_NAME = "Nexus-Ark"
    DISABLED_MESSAGE = "改造版のため、本家からのアップデート機能は停止しています。"

    def __init__(self, update_url=None):
        # Keep the call signature, but never use a configured update server.
        self.current_version = VersionManager.get_current_version()
        self.update_url = None
        self.client = None

    def is_configured(self):
        return False

    def check_for_updates(self):
        return None, self.DISABLED_MESSAGE

    def download_and_apply(self, progress_hook=None):
        return False, self.DISABLED_MESSAGE

    def trigger_restart(self):
        """
        アプリケーションを明示的に再起動します。
        exit code 123 を返して終了し、ランチャーに後継処理を任せます。
        """
        logger.info("Restarting application (exit code 123)...")
        import threading
        import time
        import os

        # 更新後の再起動では新規タブを開かず、更新適用ボタンが仕込んだ旧タブ側の
        # ポーリングJSによる同一タブリロードに委ねる。ランチャー再起動では環境変数を
        # 引き継げないため、ファイルマーカーで新プロセスへ伝える。
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            cache_dir = os.path.join(base_dir, "cache")
            os.makedirs(cache_dir, exist_ok=True)
            with open(os.path.join(cache_dir, "restart_pending.marker"), "w", encoding="utf-8") as f:
                f.write(str(time.time()))
        except Exception as e:
            logger.warning(f"Failed to write restart marker: {e}")

        def _delayed_exit():
            time.sleep(5)
            os._exit(123)

        threading.Thread(target=_delayed_exit, daemon=True).start()

    @classmethod
    def quick_check(cls):
        return None, cls.DISABLED_MESSAGE
