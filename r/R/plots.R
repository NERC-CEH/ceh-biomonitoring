# The report's charts in ggplot2, in the same style and colours as the Python report (both take them
# from the report data's text.json). One measure per chart: activity and temperature are separate panels.

#' The report style (font and UKCEH colours), from the report data
#' @param data the list from `read_report_data()`
#' @export
report_style <- function(data = NULL) {
  s <- if (!is.null(data) && length(data$text$style)) data$text$style else
    list(font = "Arial", ink = "#000000", ink_2 = "#4d4d4d", grid = "#e3e3e3", mint = "#D6EAE6",
         neutral = "#bdbdbd", main = "#133b64",
         categorical = c("#133b64", "#f4c03d", "#477AE2", "#e76124", "#67ccea", "#7f1518", "#4db264", "#cfbcd5"))
  s
}

.theme <- function(s) {
  ggplot2::theme_minimal(base_family = s$font, base_size = 11) +
    ggplot2::theme(panel.grid.minor = ggplot2::element_blank(), panel.grid.major.x = ggplot2::element_blank(),
                   panel.grid.major.y = ggplot2::element_line(colour = s$grid),
                   axis.text = ggplot2::element_text(colour = s$ink_2),
                   axis.title = ggplot2::element_text(colour = s$ink_2), legend.position = "top",
                   legend.justification = "left", legend.title = ggplot2::element_blank())
}

.nights <- function(data, deployment) {
  n <- data$nights[data$nights$deployment_id == deployment, , drop = FALSE]
  if (!"in_deployment" %in% names(n)) n$in_deployment <- TRUE
  n$in_deployment <- as.logical(n$in_deployment)
  n[order(n$night), , drop = FALSE]
}

#' Hours working each night
#' @param data the list from `read_report_data()`
#' @param deployment the deployment's id
#' @export
plot_working <- function(data, deployment) {
  s <- report_style(data)
  n <- .nights(data, deployment)
  n$when <- ifelse(n$in_deployment, "during the deployment", "outside it (e.g. set-up tests)")
  ggplot2::ggplot(n, ggplot2::aes(night, hours_worked, fill = when)) +
    ggplot2::geom_col(width = 0.8) +
    ggplot2::scale_fill_manual(values = c("during the deployment" = s$main,
                                          "outside it (e.g. set-up tests)" = s$neutral)) +
    ggplot2::scale_x_date(date_labels = "%b", date_breaks = "1 month") +
    ggplot2::labs(x = NULL, y = "hours working") + .theme(s)
}

#' Activity per hour working, each night
#' @inheritParams plot_working
#' @export
plot_activity <- function(data, deployment) {
  s <- report_style(data)
  n <- .nights(data, deployment)
  n <- n[n$in_deployment, , drop = FALSE]
  unit <- data$text$labels$unit %||% "individuals"
  ggplot2::ggplot(n, ggplot2::aes(night, individuals_per_hour)) +
    ggplot2::geom_col(width = 0.8, fill = s$main) +
    ggplot2::scale_x_date(date_labels = "%b", date_breaks = "1 month") +
    ggplot2::labs(x = NULL, y = paste(unit, "per hour")) + .theme(s)
}

#' Mean temperature while working, each night (its own chart: never a second axis)
#' @inheritParams plot_working
#' @export
plot_temperature <- function(data, deployment) {
  s <- report_style(data)
  n <- .nights(data, deployment)
  n <- n[n$in_deployment & !is.na(n$temperature_mean_c), , drop = FALSE]
  if (!nrow(n)) return(NULL)
  ggplot2::ggplot(n, ggplot2::aes(night, temperature_mean_c)) +
    ggplot2::geom_line(colour = s$categorical[4], linewidth = 0.8) +
    ggplot2::geom_point(colour = s$categorical[4], size = 1.2) +
    ggplot2::scale_x_date(date_labels = "%b", date_breaks = "1 month") +
    ggplot2::labs(x = NULL, y = "mean temperature\nwhile working (\u00b0C)") + .theme(s)
}

.hbars <- function(labels, values, xlab, s) {
  d <- data.frame(label = factor(labels, levels = rev(labels)), value = values)
  ggplot2::ggplot(d, ggplot2::aes(value, label)) +
    ggplot2::geom_col(fill = s$main, width = 0.7) +
    ggplot2::geom_text(ggplot2::aes(label = format(value, big.mark = ",")), hjust = -0.15, size = 3,
                       colour = s$ink_2) +
    ggplot2::scale_x_continuous(expand = ggplot2::expansion(mult = c(0, 0.12))) +
    ggplot2::labs(x = xlab, y = NULL) + .theme(s) +
    ggplot2::theme(panel.grid.major.y = ggplot2::element_blank(),
                   panel.grid.major.x = ggplot2::element_line(colour = s$grid))
}

#' Images: individual insects in each group (moths together, other insects by order)
#' @inheritParams plot_working
#' @export
plot_groups <- function(data, deployment) {
  s <- report_style(data)
  sp <- data$species[data$species$deployment_id == deployment, , drop = FALSE]
  if (!nrow(sp)) return(NULL)
  grp <- ifelse(sp$kind == "other insect", sp$taxon, "Moths")
  g <- sort(tapply(sp$individuals, grp, sum), decreasing = TRUE)
  if (length(g) > 9) g <- c(g[1:8], "all other groups" = sum(g[-(1:8)]))
  .hbars(names(g), as.numeric(g), "individual insects", s)
}

#' The most often recorded species
#' @inheritParams plot_working
#' @param n how many (default 20)
#' @export
plot_species <- function(data, deployment, n = 20) {
  s <- report_style(data)
  sp <- data$species[data$species$deployment_id == deployment & data$species$kind != "other insect", , drop = FALSE]
  if (!nrow(sp)) return(NULL)
  sp <- utils::head(sp[order(-sp$individuals), , drop = FALSE], n)
  nm <- if ("common_name" %in% names(sp)) ifelse(!is.na(sp$common_name) & nzchar(sp$common_name),
                                                 paste0(sp$common_name, " (", sp$taxon, ")"), sp$taxon) else sp$taxon
  .hbars(nm, sp$individuals, data$text$labels$unit %||% "individuals", s)
}
