-- ===========================================================================
-- SYNODOS | 04 - CAMADA ANALITICA (VIEWS E INDICADORES)
-- ---------------------------------------------------------------------------
-- Views curadas que o dashboard e o Select AI consomem. Nomes de colunas em
-- portugues e autoexplicativos: e o vocabulario que o modelo de linguagem
-- usa para traduzir a pergunta do gestor em SQL.
-- ===========================================================================

-- ------------------------------------------------- 1. PANORAMA CONSOLIDADO
CREATE OR REPLACE VIEW vw_panorama_geral AS
SELECT
    COUNT(*)                                        AS total_internacoes,
    COUNT(DISTINCT f.competencia)                   AS competencias_analisadas,
    COUNT(DISTINCT f.co_cnes)                       AS estabelecimentos_ativos,
    ROUND(AVG(f.qt_dias_permanencia), 1)            AS permanencia_media_dias,
    MEDIAN(f.qt_dias_permanencia)                   AS permanencia_mediana_dias,
    ROUND(AVG(f.nu_idade), 1)                       AS idade_media,
    ROUND(SUM(f.fl_obito) / COUNT(*) * 100, 2)      AS taxa_mortalidade_pct,
    ROUND(SUM(f.fl_permanencia_prolongada) / COUNT(*) * 100, 1)
                                                    AS internacoes_longas_pct,
    ROUND(SUM(f.vl_total_aih), 2)                   AS custo_total_reais,
    ROUND(AVG(f.vl_total_aih), 2)                   AS custo_medio_aih_reais
FROM fato_internacao f;

-- --------------------------------------------------- 2. SERIE TEMPORAL
CREATE OR REPLACE VIEW vw_serie_temporal AS
SELECT
    f.competencia,
    t.ano,
    t.mes,
    t.dt_competencia,
    COUNT(*)                                     AS qt_internacoes,
    ROUND(AVG(f.qt_dias_permanencia), 1)         AS permanencia_media,
    SUM(f.fl_obito)                              AS qt_obitos,
    ROUND(SUM(f.vl_total_aih), 2)                AS custo_total,
    -- media movel de 3 competencias (funcao analitica)
    ROUND(AVG(COUNT(*)) OVER (
        ORDER BY f.competencia ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
    ), 1)                                        AS media_movel_3m,
    -- variacao percentual sobre a competencia anterior
    ROUND(
        (COUNT(*) - LAG(COUNT(*)) OVER (ORDER BY f.competencia))
        / NULLIF(LAG(COUNT(*)) OVER (ORDER BY f.competencia), 0) * 100
    , 2)                                         AS variacao_mensal_pct
FROM fato_internacao f
JOIN dim_tempo t ON t.competencia = f.competencia
GROUP BY f.competencia, t.ano, t.mes, t.dt_competencia;

-- --------------------------------------- 3. TAXA POR 10 MIL HABITANTES
CREATE OR REPLACE VIEW vw_taxa_por_uf AS
SELECT
    t.sg_uf,
    t.nm_uf,
    t.regiao,
    t.populacao_2022,
    COUNT(*)                                          AS qt_internacoes,
    ROUND(
        COUNT(*) / t.populacao_2022 * 10000
        / (COUNT(DISTINCT f.competencia) / 12)
    , 2)                                              AS internacoes_por_10k_ano,
    ROUND(AVG(f.qt_dias_permanencia), 1)              AS permanencia_media,
    ROUND(SUM(f.vl_total_aih) / t.populacao_2022, 2)  AS custo_per_capita,
    ROUND(SUM(f.fl_obito) / COUNT(*) * 100, 2)        AS taxa_mortalidade_pct
FROM fato_internacao f
JOIN dim_territorio t ON t.sg_uf = f.sg_uf
GROUP BY t.sg_uf, t.nm_uf, t.regiao, t.populacao_2022;

-- ------------------------------------------------ 4. PERFIL DIAGNOSTICO
CREATE OR REPLACE VIEW vw_perfil_diagnostico AS
SELECT
    f.cid_grupo,
    c.descricao,
    c.grupo_cid,
    c.gravidade_relativa,
    COUNT(*)                                        AS qt_internacoes,
    ROUND(AVG(f.qt_dias_permanencia), 1)            AS permanencia_media,
    SUM(f.qt_dias_permanencia)                      AS dias_leito_consumidos,
    ROUND(AVG(f.nu_idade), 1)                       AS idade_media,
    ROUND(SUM(f.vl_total_aih), 2)                   AS custo_total,
    ROUND(RATIO_TO_REPORT(COUNT(*)) OVER () * 100, 2)
                                                    AS pct_internacoes,
    ROUND(
        RATIO_TO_REPORT(SUM(f.qt_dias_permanencia)) OVER () * 100
    , 2)                                            AS pct_dias_leito
FROM fato_internacao f
LEFT JOIN dim_cid10 c ON c.cid10 = f.cid_grupo
GROUP BY f.cid_grupo, c.descricao, c.grupo_cid, c.gravidade_relativa;

-- ------------------------------------------------- 5. OCUPACAO DA REDE
CREATE OR REPLACE VIEW vw_ocupacao_rede AS
WITH demanda AS (
    SELECT
        f.sg_uf,
        SUM(f.qt_dias_permanencia)     AS dias_paciente,
        COUNT(*)                       AS qt_internacoes,
        COUNT(DISTINCT f.competencia)  AS qt_competencias
    FROM fato_internacao f
    GROUP BY f.sg_uf
),
rede AS (
    SELECT
        e.sg_uf,
        SUM(e.qt_leitos_sus)                                  AS qt_leitos,
        COUNT(*)                                              AS qt_unidades,
        SUM(CASE WHEN e.ds_tipo_unidade = 'CAPS' THEN 1 ELSE 0 END)
                                                              AS qt_caps
    FROM dim_estabelecimento e
    GROUP BY e.sg_uf
)
SELECT
    d.sg_uf,
    t.nm_uf,
    t.regiao,
    d.qt_internacoes,
    r.qt_leitos,
    r.qt_caps,
    r.qt_unidades,
    ROUND(
        d.dias_paciente / NULLIF(r.qt_leitos * d.qt_competencias * 30.44, 0)
        * 100
    , 1)                                            AS taxa_ocupacao_pct,
    ROUND(r.qt_leitos / t.populacao_2022 * 10000, 2)
                                                    AS leitos_por_10k_hab,
    ROUND(r.qt_caps / t.populacao_2022 * 100000, 2)
                                                    AS caps_por_100k_hab
FROM demanda d
JOIN rede r          ON r.sg_uf = d.sg_uf
JOIN dim_territorio t ON t.sg_uf = d.sg_uf;

-- --------------------------- 6. INDICE DE PRESSAO ASSISTENCIAL (IPA)
-- Indicador composto proprio: normaliza tres dimensoes entre 0 e 100 e
-- pondera demanda (50%), complexidade (30%) e escassez de leitos (20%).
CREATE OR REPLACE VIEW vw_pressao_assistencial AS
WITH base AS (
    SELECT
        x.sg_uf, x.nm_uf, x.regiao,
        x.internacoes_por_10k_ano,
        x.permanencia_media,
        o.leitos_por_10k_hab,
        o.taxa_ocupacao_pct,
        o.qt_leitos,
        o.qt_caps,
        x.qt_internacoes
    FROM vw_taxa_por_uf x
    JOIN vw_ocupacao_rede o ON o.sg_uf = x.sg_uf
),
limites AS (
    SELECT
        MIN(internacoes_por_10k_ano) AS min_dem,
        MAX(internacoes_por_10k_ano) AS max_dem,
        MIN(permanencia_media)       AS min_perm,
        MAX(permanencia_media)       AS max_perm,
        MIN(leitos_por_10k_hab)      AS min_leito,
        MAX(leitos_por_10k_hab)      AS max_leito
    FROM base
),
normalizado AS (
    SELECT
        b.*,
        ROUND((b.internacoes_por_10k_ano - l.min_dem)
              / NULLIF(l.max_dem - l.min_dem, 0) * 100, 1) AS n_demanda,
        ROUND((b.permanencia_media - l.min_perm)
              / NULLIF(l.max_perm - l.min_perm, 0) * 100, 1) AS n_complexidade,
        ROUND(100 - (b.leitos_por_10k_hab - l.min_leito)
              / NULLIF(l.max_leito - l.min_leito, 0) * 100, 1) AS n_escassez
    FROM base b CROSS JOIN limites l
)
SELECT
    n.*,
    ROUND(
        n.n_demanda * 0.5 + n.n_complexidade * 0.3 + n.n_escassez * 0.2
    , 1)                                              AS indice_pressao,
    CASE
        WHEN n.n_demanda * 0.5 + n.n_complexidade * 0.3
           + n.n_escassez * 0.2 >= 75 THEN 'Critica'
        WHEN n.n_demanda * 0.5 + n.n_complexidade * 0.3
           + n.n_escassez * 0.2 >= 50 THEN 'Alta'
        WHEN n.n_demanda * 0.5 + n.n_complexidade * 0.3
           + n.n_escassez * 0.2 >= 25 THEN 'Moderada'
        ELSE 'Baixa'
    END                                               AS classificacao,
    RANK() OVER (
        ORDER BY n.n_demanda * 0.5 + n.n_complexidade * 0.3
               + n.n_escassez * 0.2 DESC
    )                                                 AS ranking
FROM normalizado n;

-- ------------------------------------- 7. RANKING DE UNIDADES CRITICAS
CREATE OR REPLACE VIEW vw_ranking_unidades AS
SELECT
    e.co_cnes,
    e.nm_estabelecimento,
    e.ds_tipo_unidade,
    e.sg_uf,
    e.qt_leitos_sus,
    COUNT(*)                                        AS qt_internacoes,
    ROUND(AVG(f.qt_dias_permanencia), 1)            AS permanencia_media,
    SUM(f.qt_dias_permanencia)                      AS dias_leito,
    ROUND(
        SUM(f.qt_dias_permanencia)
        / NULLIF(e.qt_leitos_sus * COUNT(DISTINCT f.competencia) * 30.44, 0)
        * 100
    , 1)                                            AS ocupacao_estimada_pct,
    RANK() OVER (ORDER BY COUNT(*) DESC)            AS ranking_volume
FROM fato_internacao f
JOIN dim_estabelecimento e ON e.co_cnes = f.co_cnes
WHERE e.qt_leitos_sus > 0
GROUP BY e.co_cnes, e.nm_estabelecimento, e.ds_tipo_unidade,
         e.sg_uf, e.qt_leitos_sus;

-- --------------------------------------------- 8. PERFIL DEMOGRAFICO
CREATE OR REPLACE VIEW vw_perfil_demografico AS
SELECT
    f.faixa_etaria,
    f.ds_sexo,
    COUNT(*)                                    AS qt_internacoes,
    ROUND(AVG(f.qt_dias_permanencia), 1)        AS permanencia_media,
    ROUND(RATIO_TO_REPORT(COUNT(*)) OVER () * 100, 2) AS pct
FROM fato_internacao f
GROUP BY f.faixa_etaria, f.ds_sexo;

-- ------------------------------------------------------- COMENTARIOS
COMMENT ON TABLE vw_pressao_assistencial IS
    'Indice de Pressao Assistencial por UF: quanto maior, mais sobrecarregada a rede de saude mental e maior a prioridade de investimento';
COMMENT ON TABLE vw_taxa_por_uf IS
    'Internacoes por 10 mil habitantes por ano em cada estado, permitindo comparacao justa entre UFs de tamanhos diferentes';
COMMENT ON TABLE vw_ocupacao_rede IS
    'Taxa de ocupacao dos leitos de saude mental e densidade de CAPS por estado';
