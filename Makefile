.PHONY: help setup amostra oficial pipeline analise dashboard limpar teste

help:
	@echo "Synodos - comandos disponiveis"
	@echo ""
	@echo "  make setup      instala as dependencias"
	@echo "  make amostra    gera a amostra calibrada (modo offline)"
	@echo "  make oficial    baixa dados reais do DATASUS e do CNES"
	@echo "  make pipeline   executa ETL completo + indicadores"
	@echo "  make analise    roda EDA e os modelos analiticos"
	@echo "  make dashboard  abre o painel Streamlit"
	@echo "  make tudo       amostra + pipeline + analise"
	@echo "  make teste      valida o pipeline ponta a ponta"
	@echo "  make limpar     remove dados gerados"

setup:
	pip install -r requirements.txt

amostra:
	python -m src.ingestao.gerar_amostra
	python -m src.ingestao.ingest_csv

oficial:
	python -m src.ingestao.ingest_sih
	python -m src.ingestao.ingest_cnes
	python -m src.ingestao.ingest_csv

pipeline:
	python -m src.etl.tratamento
	python -m src.etl.integracao
	python -m src.etl.indicadores

analise:
	python -m src.analytics.eda
	python -m src.analytics.modelos

tudo: amostra pipeline analise

dashboard:
	streamlit run dashboard/app.py

teste:
	python scripts/validar_pipeline.py

limpar:
	rm -rf data/raw/* data/processed/* data/exports/* assets/graficos/*
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@echo "Dados gerados removidos."
