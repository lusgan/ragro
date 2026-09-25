@echo off
REM Avaliação do Agente Q&A: executa a rodada, pontua e abre o relatório.
REM Uso:  avaliar            (conjunto completo, ~1h)
REM       avaliar --limite 5 (amostra rápida)
REM Demais opções em eval\README.md
"%~dp0venv\Scripts\python.exe" -m eval.avaliar %*
