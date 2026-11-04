# Etapa 2. Arrow agrega el Parquet sin cargar los 5,6 millones de filas en R.
suppressPackageStartupMessages({
  library(arrow)
  library(dplyr)
  library(ggplot2)
  library(sf)
})

raiz <- normalizePath(getwd(), winslash = "/", mustWork = TRUE)
entrada <- file.path(raiz, "Data_Processed", "nacimientos_preparados.parquet")
poblacion_csv <- file.path(raiz, "Data_Processed", "poblacion_departamental.csv")
geometria <- file.path(raiz, "Municipios", "departamentos_mgn2018.geojson")
tablas <- file.path(raiz, "Reports", "output", "tables")
figuras <- file.path(raiz, "Reports", "output", "figures")
stopifnot(file.exists(entrada), file.exists(poblacion_csv), file.exists(geometria))
dir.create(tablas, recursive = TRUE, showWarnings = FALSE)
dir.create(figuras, recursive = TRUE, showWarnings = FALSE)

datos <- arrow::open_dataset(entrada, format = "parquet")
base <- datos |>
  filter(RESIDE_COLOMBIA == TRUE, !is.na(DEPTO_RES_COD),
         ANIO >= 2015L, ANIO <= 2023L)
conteo <- function(grupos) {
  base |> group_by(across(all_of(grupos))) |>
    summarise(NACIMIENTOS = n(), .groups = "drop") |> collect() |>
    as.data.frame()
}

anual <- conteo("ANIO")
departamentos <- conteo(c("ANIO", "DEPTO_RES_COD", "DEPTO_RES_NOMBRE"))
edades <- conteo(c("ANIO", "EDAD_MADRE_GRUPO"))
areas <- conteo(c("ANIO", "AREA_RES_GRUPO"))
auditoria <- conteo(c("ANIO", "DIVIPOLA_2025"))

poblacion <- read.csv(poblacion_csv, colClasses = c("integer", "character", "numeric", "character"),
                      fileEncoding = "UTF-8")
stopifnot(nrow(poblacion) == 297L, !anyDuplicated(poblacion[c("ANIO", "DEPTO_RES_COD")]))
departamentos <- departamentos |>
  left_join(poblacion[c("ANIO", "DEPTO_RES_COD", "POBLACION")],
            by = c("ANIO", "DEPTO_RES_COD")) |>
  mutate(TASA_POR_MIL = 1000 * NACIMIENTOS / POBLACION)
if (anyNA(departamentos$POBLACION) || nrow(departamentos) != 297L) {
  stop("Faltan denominadores o departamentos en la tabla de tasas.")
}
denominador_nacional <- poblacion |>
  group_by(ANIO) |> summarise(POBLACION = sum(POBLACION), .groups = "drop")
anual <- anual |>
  left_join(denominador_nacional, by = "ANIO") |>
  mutate(TASA_POR_MIL = 1000 * NACIMIENTOS / POBLACION)
stopifnot(nrow(anual) == 9L,
          sum(anual$NACIMIENTOS) == sum(departamentos$NACIMIENTOS),
          sum(anual$NACIMIENTOS) == sum(edades$NACIMIENTOS),
          sum(anual$NACIMIENTOS) == sum(areas$NACIMIENTOS),
          sum(anual$NACIMIENTOS) == sum(auditoria$NACIMIENTOS))
edades <- edades |> left_join(anual[c("ANIO", "NACIMIENTOS")], by = "ANIO",
                             suffix = c("", "_ANUAL")) |>
  mutate(PORCENTAJE = 100 * NACIMIENTOS / NACIMIENTOS_ANUAL)
areas <- areas |> left_join(anual[c("ANIO", "NACIMIENTOS")], by = "ANIO",
                           suffix = c("", "_ANUAL")) |>
  mutate(PORCENTAJE = 100 * NACIMIENTOS / NACIMIENTOS_ANUAL)

write.csv(anual, file.path(tablas, "resumen_anual.csv"), row.names = FALSE, fileEncoding = "UTF-8")
write.csv(departamentos, file.path(tablas, "departamentos_anual.csv"), row.names = FALSE,
          fileEncoding = "UTF-8")
write.csv(edades, file.path(tablas, "edad_anual.csv"), row.names = FALSE, fileEncoding = "UTF-8")
write.csv(areas, file.path(tablas, "area_anual.csv"), row.names = FALSE, fileEncoding = "UTF-8")
write.csv(auditoria, file.path(tablas, "auditoria_divipola.csv"), row.names = FALSE,
          fileEncoding = "UTF-8")

tema <- theme_minimal(base_size = 12) +
  theme(plot.title.position = "plot", panel.grid.minor = element_blank(),
        plot.caption = element_text(hjust = 0))
grafico_serie <- ggplot(anual, aes(ANIO, TASA_POR_MIL)) +
  geom_line(color = "#087E8B", linewidth = 1.1) +
  geom_point(color = "#087E8B", size = 2.5) +
  scale_x_continuous(breaks = 2015:2023) +
  labs(title = "Nacimientos registrados por 1.000 habitantes",
       subtitle = "Madres residentes en Colombia con departamento conocido",
       x = "Año del nacimiento", y = "Tasa por 1.000 habitantes",
       caption = "Fuente: microdatos de nacimientos y proyecciones departamentales del DANE. Cálculo propio.") + tema
ggsave(file.path(figuras, "serie_tasa.png"), grafico_serie, width = 9, height = 5, dpi = 160)

orden_edades <- c(paste0(seq(10, 50, 5), "–", seq(14, 54, 5)), "Sin información")
grafico_edad <- edades |>
  filter(ANIO %in% c(2015L, 2023L)) |>
  mutate(EDAD_MADRE_GRUPO = factor(EDAD_MADRE_GRUPO, levels = orden_edades)) |>
  ggplot(aes(EDAD_MADRE_GRUPO, PORCENTAJE, fill = factor(ANIO))) +
  geom_col(position = "dodge") +
  scale_fill_manual(values = c("2015" = "#087E8B", "2023" = "#F4A261"), name = "Año") +
  labs(title = "Edad materna registrada", x = "Grupo de edad", y = "% de nacimientos",
       caption = "Denominador: nacimientos de madres residentes en Colombia con departamento conocido.") +
  tema + theme(axis.text.x = element_text(angle = 45, hjust = 1))
ggsave(file.path(figuras, "edad_2015_2023.png"), grafico_edad, width = 9, height = 5, dpi = 160)

grafico_area <- areas |>
  filter(ANIO %in% c(2015L, 2023L)) |>
  ggplot(aes(factor(ANIO), PORCENTAJE, fill = AREA_RES_GRUPO)) +
  geom_col() +
  scale_fill_manual(values = c("Cabecera municipal" = "#087E8B", "Centro poblado" = "#4DAA8A",
                               "Rural disperso" = "#F4A261", "Sin información" = "#777777")) +
  labs(title = "Área de residencia habitual de la madre", x = "Año", y = "% de nacimientos",
       fill = "Área", caption = "La categoría sin información permanece en el denominador.") + tema
ggsave(file.path(figuras, "area_2015_2023.png"), grafico_area, width = 9, height = 5, dpi = 160)

mapa <- sf::st_read(geometria, quiet = TRUE)
stopifnot(nrow(mapa) == 33L, !anyDuplicated(mapa$DEPTO_RES_COD))
mapas <- mapa |>
  left_join(departamentos |> filter(ANIO %in% c(2015L, 2023L)), by = "DEPTO_RES_COD")
stopifnot(nrow(mapas) == 66L, !anyNA(mapas$TASA_POR_MIL))
grafico_mapa <- ggplot(mapas) +
  geom_sf(aes(fill = TASA_POR_MIL), color = "white", linewidth = 0.1) +
  facet_wrap(~ ANIO) +
  scale_fill_viridis_c(option = "C", name = "Por 1.000") +
  labs(title = "Tasa de nacimientos registrados por departamento",
       subtitle = "Departamento de residencia habitual de la madre",
       caption = "MGN 2018 y proyecciones poblacionales del DANE. Límites simplificados para visualización.") +
  tema + theme(axis.text = element_blank(), axis.ticks = element_blank(), panel.grid = element_blank())
ggsave(file.path(figuras, "mapa_tasa_2015_2023.png"), grafico_mapa, width = 10, height = 6, dpi = 160)

cat(sprintf("Análisis R terminado: %s registros con residencia departamental; 5 tablas y 4 figuras.\n",
            formatC(sum(anual$NACIMIENTOS), format = "d", big.mark = ".", decimal.mark = ",")))
