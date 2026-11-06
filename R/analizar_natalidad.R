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
media_edad <- edades |>
  filter(EDAD_MADRE_GRUPO != "Sin información") |>
  mutate(PUNTO_MEDIO = as.integer(substr(EDAD_MADRE_GRUPO, 1L, 2L)) + 2L) |>
  group_by(ANIO) |>
  summarise(NACIMIENTOS_CON_EDAD = sum(NACIMIENTOS),
            MEDIA_APROXIMADA = sum(NACIMIENTOS * PUNTO_MEDIO) / sum(NACIMIENTOS),
            .groups = "drop") |>
  left_join(anual |> select(ANIO, TOTAL_ANUAL = NACIMIENTOS), by = "ANIO") |>
  mutate(SIN_INFORMACION = TOTAL_ANUAL - NACIMIENTOS_CON_EDAD) |>
  select(ANIO, NACIMIENTOS_CON_EDAD, SIN_INFORMACION, MEDIA_APROXIMADA)
stopifnot(nrow(media_edad) == 9L, !anyNA(media_edad$MEDIA_APROXIMADA),
          all(media_edad$SIN_INFORMACION >= 0L))

write.csv(anual, file.path(tablas, "resumen_anual.csv"), row.names = FALSE, fileEncoding = "UTF-8")
write.csv(departamentos, file.path(tablas, "departamentos_anual.csv"), row.names = FALSE,
          fileEncoding = "UTF-8")
write.csv(edades, file.path(tablas, "edad_anual.csv"), row.names = FALSE, fileEncoding = "UTF-8")
write.csv(media_edad, file.path(tablas, "media_edad_anual.csv"), row.names = FALSE,
          fileEncoding = "UTF-8")
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

orden_edades <- c("10–14", "15–19", "20–24", "25–29", "30–34", "35–39", "40+")
edades_serie <- edades |>
  filter(EDAD_MADRE_GRUPO != "Sin información") |>
  mutate(EDAD_MADRE_GRUPO = if_else(
    EDAD_MADRE_GRUPO %in% c("40–44", "45–49", "50–54"),
    "40+", EDAD_MADRE_GRUPO
  )) |>
  group_by(ANIO, EDAD_MADRE_GRUPO) |>
  summarise(NACIMIENTOS = sum(NACIMIENTOS), .groups = "drop") |>
  mutate(EDAD_MADRE_GRUPO = factor(EDAD_MADRE_GRUPO, levels = orden_edades))
stopifnot(nrow(edades_serie) == 63L, !anyNA(edades_serie$EDAD_MADRE_GRUPO))
grafico_edad <- ggplot(edades_serie,
                       aes(ANIO, NACIMIENTOS, colour = EDAD_MADRE_GRUPO)) +
  geom_line(linewidth = 1.1) + geom_point(size = 2) +
  scale_x_continuous(breaks = 2015:2023) +
  scale_y_continuous(labels = scales::label_number(scale = 1e-3, suffix = " mil")) +
  scale_colour_manual(values = c(
    "10–14" = "#788B9A", "15–19" = "#FF504F", "20–24" = "#0056A6",
    "25–29" = "#002C49", "30–34" = "#087E8B", "35–39" = "#B8860B",
    "40+" = "#7A5AA8"
  ), name = "Edad de la madre") +
  labs(title = "Nacimientos por grupo de edad materna, año a año",
       subtitle = "Madres residentes en Colombia con departamento conocido",
       x = "Año", y = "Nacimientos",
       caption = "40+ agrupa 40–54 años. Se excluyen edades sin información de esta figura.") +
  tema + theme(legend.position = "bottom")
ggsave(file.path(figuras, "edad_serie_2015_2023.png"),
       grafico_edad, width = 10, height = 5.5, dpi = 160)

grafico_area <- areas |>
  filter(ANIO %in% c(2015L, 2023L)) |>
  ggplot(aes(factor(ANIO), PORCENTAJE, fill = AREA_RES_GRUPO)) +
  geom_col() +
  scale_fill_manual(values = c("Cabecera municipal" = "#087E8B", "Centro poblado" = "#4DAA8A",
                               "Rural disperso" = "#F4A261", "Sin información" = "#777777")) +
  labs(title = "Área de residencia habitual de la madre", x = "Año", y = "% de nacimientos",
       fill = "Área", caption = "La categoría sin información permanece en el denominador.") + tema
ggsave(file.path(figuras, "area_2015_2023.png"), grafico_area, width = 9, height = 5, dpi = 160)

top5_codigos <- departamentos |>
  filter(ANIO == 2023L) |>
  slice_max(NACIMIENTOS, n = 5L, with_ties = FALSE) |>
  pull(DEPTO_RES_COD)
serie_top5 <- departamentos |>
  filter(DEPTO_RES_COD %in% top5_codigos) |>
  mutate(DEPTO_RES_NOMBRE = factor(
    DEPTO_RES_NOMBRE,
    levels = c("Bogotá, D.C.", "Antioquia", "Valle del Cauca", "Atlántico", "Bolívar")
  ))
stopifnot(nrow(serie_top5) == 45L, !anyNA(serie_top5$DEPTO_RES_NOMBRE))
grafico_serie_departamentos <- ggplot(
  serie_top5, aes(ANIO, NACIMIENTOS, colour = DEPTO_RES_NOMBRE)
) +
  geom_line(linewidth = 1.1) + geom_point(size = 2) +
  scale_x_continuous(breaks = 2015:2023) +
  scale_y_continuous(labels = scales::label_number(scale = 1e-3, suffix = " mil")) +
  scale_colour_manual(values = c(
    "Bogotá, D.C." = "#002C49", "Antioquia" = "#0056A6",
    "Valle del Cauca" = "#FF504F", "Atlántico" = "#B8860B", "Bolívar" = "#087E8B"
  ), name = "Departamento") +
  labs(title = "Nacimientos registrados: cinco departamentos con más casos en 2023",
       subtitle = "Serie anual según residencia habitual de la madre",
       x = "Año", y = "Nacimientos",
       caption = "Fuente: microdatos de nacimientos del DANE. Conteos del análisis territorial.") + tema
ggsave(file.path(figuras, "serie_departamentos_top5.png"),
       grafico_serie_departamentos, width = 10, height = 5.5, dpi = 160)

mapa <- sf::st_read(geometria, quiet = TRUE)
stopifnot(nrow(mapa) == 33L, !anyDuplicated(mapa$DEPTO_RES_COD))
mapas <- mapa |>
  left_join(departamentos |> filter(ANIO %in% c(2015L, 2023L)), by = "DEPTO_RES_COD")
stopifnot(nrow(mapas) == 66L, !anyNA(mapas$TASA_POR_MIL))
stopifnot(!anyNA(mapas$NACIMIENTOS))
grafico_mapa_conteo <- ggplot(mapas) +
  geom_sf(aes(fill = NACIMIENTOS), color = "white", linewidth = 0.1) +
  facet_wrap(~ ANIO) +
  scale_fill_gradientn(
    colours = c("#C9413A", "#F3D05B", "#238B53"),
    transform = "sqrt", limits = c(0, max(mapas$NACIMIENTOS)),
    breaks = c(0, 10000, 20000, 40000, 60000, 100000),
    labels = scales::label_number(big.mark = ".", decimal.mark = ","),
    name = "Nacimientos"
  ) +
  labs(title = "Nacimientos registrados por departamento",
       subtitle = "Rojo: menos nacimientos · verde: más nacimientos",
       caption = "Misma escala para 2015 y 2023. MGN 2018 y microdatos de nacimientos del DANE.") +
  tema + theme(axis.text = element_blank(), axis.ticks = element_blank(), panel.grid = element_blank())
ggsave(file.path(figuras, "mapa_nacimientos_semaforo_2015_2023.png"),
       grafico_mapa_conteo, width = 10, height = 5, dpi = 160)

grafico_mapa <- ggplot(mapas) +
  geom_sf(aes(fill = TASA_POR_MIL), color = "white", linewidth = 0.1) +
  facet_wrap(~ ANIO) +
  scale_fill_viridis_c(option = "C", name = "Por 1.000") +
  labs(title = "Tasa de nacimientos registrados por departamento",
       subtitle = "Departamento de residencia habitual de la madre",
       caption = "MGN 2018 y proyecciones poblacionales del DANE. Límites simplificados para visualización.") +
  tema + theme(axis.text = element_blank(), axis.ticks = element_blank(), panel.grid = element_blank())
ggsave(file.path(figuras, "mapa_tasa_2015_2023.png"), grafico_mapa, width = 10, height = 6, dpi = 160)

cat(sprintf("Análisis R terminado: %s registros con residencia departamental; 6 tablas y 6 figuras.\n",
            formatC(sum(anual$NACIMIENTOS), format = "d", big.mark = ".", decimal.mark = ",")))
