# script-transcricao-videos-31-08-26

Script Python para transcrição fiel de áudio de vídeos (`.mkv`, `.mp4`, etc) usando:

1. **`faster-whisper`** local (Whisper da OpenAI) — primeira passada com `initial_prompt` injetando tema + glossário
2. **OpenRouter** (modelo de linguagem) — segunda passada que revisa grafias de termos técnicos, nomes próprios e nomes estrangeiros

A chave da fidelidade é a informação de **tema do vídeo** (+ glossário opcional) que é injetada no Whisper e usada no prompt de revisão do LLM.

---

## Requisitos

- `ffmpeg` instalado e no `PATH`
- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/) para gerenciar o ambiente
- (Opcional) Chave de API da OpenRouter (https://openrouter.ai/keys) — necessária apenas se for usar a etapa de revisão

---

## Duas formas de rodar

### 🟢 Rodando no Google Colab (recomendado)

A GPU T4 gratuita do Colab é **10-30× mais rápida** que CPU local, especialmente para o modelo `large-v3`. Para um vídeo de 1h:
- **CPU local**: 2-4h com `large-v3`, ou ~50min+ com `medium` (em float32)
- **Colab GPU**: 5-10 min com `large-v3`

Abra o notebook `notebooks/transcrever_colab.ipynb` no Colab (upload ou via GitHub) e siga as células. Ele cuida de:
1. Verificar GPU
2. Instalar ffmpeg + uv
3. Clonar o repositório (ou upload manual do zip)
4. Instalar dependências
5. **Ler a chave da OpenRouter dos [Secrets](https://colab.research.google.com/notebooks/secretmanager.ipynb) do Colab** (ícone 🔑 na barra lateral — não cole a chave no notebook)
6. Apontar para os vídeos no Google Drive (lista ou vídeo único) ou, em fallback, upload local
7. Receber tema + glossário
8. Rodar o pipeline (Whisper + revisão LLM)
9. Empacotar as saídas e oferecer download

**Sobre a chave de API:** adicione `OPENROUTER_API_KEY` (e opcionalmente `OPENROUTER_MODEL`) na aba 🔑 Secrets do Colab antes de rodar. Sem a chave, a etapa de revisão LLM é pulada automaticamente e o notebook segue só com o Whisper.

### 💻 Rodando local

```bash
uv sync
cp .env.example .env
# editar .env e preencher OPENROUTER_API_KEY (opcional)
```

**Sincronizando chaves dos Secrets do Colab para o `.env` local:**

Se você já tem as chaves configuradas nos [Secrets do Colab](https://colab.research.google.com/notebooks/secretmanager.ipynb) e quer reaproveitá-las no ambiente local:

```bash
uv run pull-secrets --dry-run   # mostra o que seria escrito
uv run pull-secrets             # escreve no .env (preserva chaves já existentes)
uv run pull-secrets --force     # sobrescreve tudo
uv run pull-secrets --manual    # prompt interativo (sem Colab)
```

O script também lê de `os.environ` como fallback (caso você tenha exportado a chave no shell).

Exemplo completo (com revisão LLM + glossário):

```bash
# glossario.txt (1 termo por linha):
#   John Preskill
#   Qubit
#   IBM Quantum
#   Shor
#   Grover

uv run transcrever "video_base/2026-08-31 02-09-08.mkv" \
    --tema "Aula de computação quântica com John Preskill sobre algoritmos de Shor e Grover" \
    --glossario glossario.txt \
    --modelo-whisper large-v3 \
    --modelo-llm "meta-llama/llama-3.3-70b-instruct:free" \
    --saida ./saidas
```

Exemplo mínimo (sem LLM, sem glossário):

```bash
uv run transcrever video.mkv --tema "Aula introdutória de computação quântica"
```

#### Acelerando em CPU

Em CPU o `faster-whisper` às vezes cai em `float32`, que é lento. Force `int8`:

```bash
uv run transcrever video.mkv --tema "..." --device cpu --compute-type int8 --modelo-whisper small
```

---

## Todas as opções

```
transcrever VIDEO [OPÇÕES]

Argumentos:
  VIDEO                              Caminho do vídeo (.mkv, .mp4, etc.)

Opções:
  --tema              -t    <str>   Tema do vídeo (obrigatório)
  --glossario         -g    <path>  Arquivo .txt, 1 termo por linha (opcional)
  --modelo-whisper          <str>   tiny, base, small, medium, large-v3
                                     [default: large-v3]
  --device                  <str>   cpu, cuda ou auto  [default: auto]
  --compute-type            <str>   int8, float16, float32 ou auto
                                     [default: auto]
  --modelo-llm              <str>   Modelo OpenRouter
                                     [default: meta-llama/llama-3.3-70b-instruct:free]
  --saida           -o      <path>  Diretório de saída
  --sem-revisao                     Pula a etapa de revisão via LLM
  --forcar                          Ignora cache e reprocessa tudo
```

---

## Saídas

Em `./saidas/<nome-do-video>/`:

| Arquivo | Conteúdo |
|---|---|
| `audio.wav` | Áudio extraído (16kHz mono) |
| `transcricao_bruta.json` | Saída bruta do Whisper com timestamps por palavra |
| `transcricao.txt` | Texto puro, revisado pelo LLM (se habilitado) |
| `transcricao.srt` | Legendas com timestamps |
| `transcricao.md` | Markdown com timestamps entre colchetes |
| `transcricao_final.json` | JSON final (texto + segmentos + metadados) |

---

## Como funciona

```
.mkv
  └─► ffmpeg extrai WAV 16kHz mono
        └─► faster-whisper transcreve (com tema no initial_prompt)
              └─► OpenRouter revisa usando tema + glossário
                    └─► gera .txt, .srt, .md, .json
```

A primeira passada do Whisper já usa o **tema do vídeo** como contexto (estilo "frase anterior"), o que reduz drasticamente erros de grafia em termos técnicos. Em seguida, o LLM aplica correções finas usando o glossário como fonte de verdade.

**Cache:** a transcrição do Whisper é cacheada por hash do áudio. Re-rodar com a mesma `--tema` ou `--modelo-llm` diferente **não reprocessa o áudio** — só refaz a revisão. Use `--forcar` para ignorar.

---

## Modelos OpenRouter gratuitos sugeridos

- `meta-llama/llama-3.3-70b-instruct:free` — bom geral
- `google/gemini-2.0-flash-exp:free` — rápido
- `qwen/qwen-2.5-72b-instruct:free` — forte em técnico
- `mistralai/mistral-small-3.1-24b-instruct:free` — leve

Modelos `:free` têm rate limit agressivo. Para vídeos longos, considere um modelo pago barato (Gemini Flash, Haiku).
