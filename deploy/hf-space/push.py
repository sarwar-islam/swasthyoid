"""Upload the demo backend to the Gradio Space: python deploy/hf-space/push.py sarwarcss/swasthyoid-api

Needs huggingface_hub and a login you did yourself. Uploads app.py, packages.txt, requirements.txt, README.md and the
swasthyoid package (no tests, data, keys or local model files). The Space is public: Vercel reaches it without a token.
"""
import pathlib
import shutil
import sys
import tempfile

from huggingface_hub import HfApi

ROOT = pathlib.Path(__file__).resolve().parents[2]
FILES = ("app.py", "packages.txt", "requirements.txt", "README.md")


def main(space_id):
    with tempfile.TemporaryDirectory() as tmp:
        stage = pathlib.Path(tmp)
        for name in FILES:
            shutil.copy(ROOT / "deploy/hf-space" / name, stage / name)
        shutil.copytree(ROOT / "swasthyoid", stage / "swasthyoid",
                        ignore=shutil.ignore_patterns("tests", "__pycache__", "*.pyc", "*.egg-info"))
        HfApi().upload_folder(repo_id=space_id, repo_type="space", folder_path=str(stage),
                              commit_message="Deploy SwasthyoID demo backend",
                              delete_patterns=["swasthyoid/**", "Dockerfile", "start.sh"])  # keeps .gitattributes
    owner, name = space_id.split("/")
    print(f"pushed: https://huggingface.co/spaces/{space_id}  API: https://{owner}-{name}.hf.space".lower())


if __name__ == "__main__":
    if len(sys.argv) != 2 or "/" not in sys.argv[1]:
        sys.exit("usage: push.py <owner>/<space-name>")
    main(sys.argv[1])
