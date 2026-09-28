#!/bin/bash
set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo ""
echo -e "${BLUE}╔══════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   Intelligent Digital Forensic AI Assistant   ║${NC}"
echo -e "${BLUE}║         Setup Script v2.0            ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════╝${NC}"
echo ""

# ── Detect OS ─────────────────────────────────────────────────────────────────
if [[ "$OSTYPE" == "darwin"* ]]; then
  OS="macos"
  echo -e "${BLUE}Platform: macOS${NC}"
elif [[ -f /etc/debian_version ]]; then
  OS="linux"
  echo -e "${BLUE}Platform: Ubuntu/Debian Linux${NC}"
else
  OS="unknown"
  echo -e "${YELLOW}Platform: Unknown — some steps may need manual intervention${NC}"
fi

# ── 1. Prerequisites ──────────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}[1/8] Checking prerequisites...${NC}"

check_cmd() {
  local cmd=$1
  local install_mac=$2
  local install_linux=$3
  if ! command -v "$cmd" &>/dev/null; then
    echo -e "${RED}✗ $cmd not found${NC}"
    if [[ "$OS" == "macos" ]]; then
      echo "  Install: $install_mac"
    else
      echo "  Install: $install_linux"
    fi
    exit 1
  fi
  echo -e "${GREEN}✓ $cmd $("$cmd" --version 2>/dev/null | head -1)${NC}"
}

check_cmd python3 \
  "brew install python3" \
  "sudo apt install python3 python3-pip python3-venv"

check_cmd node \
  "brew install node" \
  "sudo apt install nodejs npm"

if ! command -v ollama &>/dev/null; then
  echo -e "${YELLOW}⚠ Ollama not found${NC}"
  if [[ "$OS" == "macos" ]]; then
    echo "  Download from: https://ollama.com"
  else
    echo "  Install: curl -fsSL https://ollama.com/install.sh | sh"
  fi
  echo -e "${YELLOW}  Continuing — start Ollama before running the app${NC}"
else
  echo -e "${GREEN}✓ Ollama found${NC}"
fi

# ── 2. .env setup ─────────────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}[2/8] Environment configuration...${NC}"
if [ ! -f ".env" ]; then
  if [ -f ".env.example" ]; then
    cp .env.example .env
    echo -e "${GREEN}✓ Created .env from .env.example${NC}"
    echo -e "${YELLOW}  ⚠ Edit .env and set a real SECRET_KEY before use${NC}"
  else
    echo -e "${RED}✗ No .env or .env.example found${NC}"
    exit 1
  fi
else
  echo -e "${GREEN}✓ .env already exists${NC}"
fi

# ── 3. Python virtual environment ─────────────────────────────────────────────
echo ""
echo -e "${YELLOW}[3/8] Python virtual environment...${NC}"
if [ ! -d "venv" ]; then
  python3 -m venv venv
  echo -e "${GREEN}✓ Virtual environment created${NC}"
else
  echo -e "${GREEN}✓ Virtual environment exists${NC}"
fi
source venv/bin/activate

# ── 4. Python packages ────────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}[4/8] Installing Python packages...${NC}"
pip install -q --upgrade pip setuptools wheel
pip install -q -r requirements.txt
echo -e "${GREEN}✓ Python packages installed${NC}"

# ── 5. spaCy NLP model ────────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}[5/8] NLP model...${NC}"

# en_core_web_sm is NOT optional: graph_builder.py loads it at module import
# time, so without it `import backend.main` fails outright. The previous
# version of this script installed only en_core_web_lg.
#
# `python3 -m spacy download <model>` was also replaced: against the live
# spacy-models release index it resolves the model version to an empty string
# and builds the URL
#   .../releases/download/-en_core_web_lg/-en_core_web_lg.tar.gz
# which is a guaranteed 404. Pin the version explicitly instead. 3.7.1 is the
# model release built for spacy 3.7.x, which is what requirements.txt pins.
SPACY_MODEL_VERSION=3.7.1
SPACY_MODELS="en_core_web_sm en_core_web_lg"

for model in $SPACY_MODELS; do
  if python3 -c "import spacy; spacy.load('$model')" 2>/dev/null; then
    echo -e "${GREEN}✓ $model already installed${NC}"
    continue
  fi

  tarball="vendor/python/${model}-${SPACY_MODEL_VERSION}.tar.gz"
  if [ -f "$tarball" ]; then
    # vendor/ is deliberately NOT in git, so it only exists on a machine that
    # was handed the offline kit. Installing from it with --no-index against a
    # directory that is not there fails outright - which is what a fresh git
    # clone used to do.
    pip install --no-index --find-links=vendor/python "$tarball" -q
    echo -e "${GREEN}✓ $model installed from vendor${NC}"
  else
    pip install -q \
      "https://github.com/explosion/spacy-models/releases/download/${model}-${SPACY_MODEL_VERSION}/${model}-${SPACY_MODEL_VERSION}.tar.gz"
    echo -e "${GREEN}✓ $model ${SPACY_MODEL_VERSION} installed${NC}"
  fi
done

# Verify, do not assume: a silent no-op here is what made the broken download
# above look like a success on a machine where the model was already present.
for model in $SPACY_MODELS; do
  if ! python3 -c "import spacy; spacy.load('$model')" 2>/dev/null; then
    echo -e "${RED}✗ $model failed to load - the backend will not import${NC}"
    exit 1
  fi
done
echo -e "${GREEN}✓ NLP models verified loadable${NC}"

# ── 6. Data directories ───────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}[6/8] Creating data directories...${NC}"
mkdir -p data/cases
echo -e "${GREEN}✓ Directories ready${NC}"

# ── 7. Database migrations ────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}[7/8] Running database migrations...${NC}"
PYTHONPATH=. python3 backend/migrate_all.py
echo -e "${GREEN}✓ Migrations complete${NC}"

# ── 8. Frontend packages ──────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}[8/8] Frontend packages...${NC}"
# npm, NOT yarn - frontend/package-lock.json is the lockfile of record.
cd frontend && npm install --silent && cd ..
echo -e "${GREEN}✓ Frontend packages installed${NC}"

# ── Pull Ollama models ────────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}Pulling Ollama models...${NC}"

# Read model name from .env, fallback to llama3.2:3b
OLLAMA_MODEL=$(grep "^OLLAMA_MODEL=" .env 2>/dev/null \
  | cut -d= -f2 | tr -d ' ')
OLLAMA_MODEL=${OLLAMA_MODEL:-llama3.2:3b}

if command -v ollama &>/dev/null; then
  ollama pull "$OLLAMA_MODEL" && \
    echo -e "${GREEN}✓ $OLLAMA_MODEL ready${NC}"
  ollama pull nomic-embed-text && \
    echo -e "${GREEN}✓ nomic-embed-text ready${NC}"
else
  echo -e "${YELLOW}⚠ Ollama not running — pull models manually:${NC}"
  echo "  ollama pull $OLLAMA_MODEL"
  echo "  ollama pull nomic-embed-text"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║         Setup Complete! ✓            ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════╝${NC}"
echo ""
echo "Start the application (3 terminals):"
echo ""
echo -e "  ${BLUE}Terminal 1${NC} — AI Engine"
echo "    ollama serve"
echo ""
echo -e "  ${BLUE}Terminal 2${NC} — Backend"
echo "    source venv/bin/activate"
echo "    PYTHONPATH=. uvicorn backend.main:app --reload --port 8000"
echo ""
echo -e "  ${BLUE}Terminal 3${NC} — Frontend"
echo "    cd frontend && npm run dev"
echo ""
echo -e "  ${BLUE}Then open:${NC} http://localhost:3000"
echo ""
echo "  First user to register becomes Admin."
echo ""
