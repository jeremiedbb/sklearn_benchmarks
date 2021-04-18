import os
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import qgrid
from IPython.display import Markdown, display, HTML
from plotly.subplots import make_subplots

from sklearn_benchmarks.config import (
    BASE_LIB,
    BENCHMARKING_RESULTS_PATH,
    PROFILING_RESULTS_PATH,
    PLOT_HEIGHT_IN_PX,
    REPORTING_FONT_SIZE,
    SPEEDUP_COL,
    STDEV_SPEEDUP_COL,
    TIME_REPORT_PATH,
    get_full_config,
)
from sklearn_benchmarks.utils.plotting import gen_coordinates_grid, make_hover_template


class Reporting:
    """
    Runs reporting for specified estimators.
    """

    def __init__(self, config_file_path=None):
        self.config_file_path = config_file_path

    def _print_time_report(self):
        df = pd.read_csv(str(TIME_REPORT_PATH), index_col="algo")
        display(df)

    def run(self):
        config = get_full_config(config_file_path=self.config_file_path)
        reporting_config = config["reporting"]
        display(Markdown("## Time report"))
        # self._print_time_report()
        estimators = reporting_config["estimators"]
        for name, params in estimators.items():
            params["n_cols"] = reporting_config["n_cols"]
            display(Markdown(f"## {name}"))
            report = Report(**params)
            report.run()


class Report:
    """
    Runs reporting for one estimator.
    """

    def __init__(
        self,
        name="",
        against_lib="",
        split_bar=[],
        group_by=[],
        compare=[],
        n_cols=None,
    ):
        self.name = name
        self.against_lib = against_lib
        self.split_bar = split_bar
        self.group_by = group_by
        self.compare = compare
        self.n_cols = n_cols

    def _get_benchmark_df(self, lib=BASE_LIB):
        benchmarking_results_path = str(BENCHMARKING_RESULTS_PATH)
        file_path = f"{benchmarking_results_path}/{lib}_{self.name}.csv"
        return pd.read_csv(file_path)

    def _make_reporting_df(self):

        base_lib_df = self._get_benchmark_df()
        base_lib_time = base_lib_df[SPEEDUP_COL]
        base_lib_std = base_lib_df[STDEV_SPEEDUP_COL]

        against_lib_df = self._get_benchmark_df(lib=self.against_lib)
        against_lib_time = against_lib_df[SPEEDUP_COL]
        against_lib_std = against_lib_df[STDEV_SPEEDUP_COL]

        suffixes = map(lambda lib: f"_{lib}", [BASE_LIB, self.against_lib])
        merged_df = pd.merge(
            base_lib_df,
            against_lib_df[self.compare],
            left_index=True,
            right_index=True,
            suffixes=suffixes,
        )

        merged_df["speedup"] = base_lib_time / against_lib_time
        merged_df["stdev_speedup"] = (base_lib_std / base_lib_time) ** 2 + (
            against_lib_std / against_lib_time
        ) ** 2

        return merged_df

    def _make_profiling_link(self, digests):
        hyperparams_digest, dataset_digest = digests
        path = Path(
            f"{PROFILING_RESULTS_PATH}/sklearn_{hyperparams_digest}_{dataset_digest}.html"
        )
        if os.environ.get("SKLEARN_RESULTS_BASE_URL") is not None:
            base_url = os.environ.get("SKLEARN_RESULTS_BASE_URL")
        else:
            base_url = "file://"
            path = os.path.abspath(path)
        return f"<a href='{base_url}{path}' target='_blank'>See</a>"

    def _print_table(self):
        df = self._make_reporting_df()

        df["profiling"] = df[["hyperparams_digest", "dataset_digest"]].apply(
            self._make_profiling_link, axis=1
        )
        qgrid_widget = qgrid.show_grid(df, show_toolbar=True)
        display(qgrid_widget)

    def _plot(self):
        merged_df = self._make_reporting_df()
        merged_df_grouped = merged_df.groupby(self.group_by)

        n_plots = len(merged_df_grouped)
        n_rows = n_plots // self.n_cols + n_plots % self.n_cols
        coordinates = gen_coordinates_grid(n_rows, self.n_cols)

        subplot_titles = []
        for params, _ in merged_df_grouped:
            title = ""
            for index, (name, val) in enumerate(zip(self.group_by, params)):
                title += "%s: %s" % (name, val)
                if index > 0 and index % 3 == 0:
                    title += "<br>"
                elif index != len(list(zip(self.group_by, params))) - 1:
                    title += " - "

            subplot_titles.append(title)

        fig = make_subplots(
            rows=n_rows,
            cols=self.n_cols,
            subplot_titles=subplot_titles,
        )

        for (row, col), (_, df) in zip(coordinates, merged_df_grouped):
            df = df.sort_values(by=["n_samples", "n_features"])
            df = df.dropna(axis="columns")
            if self.split_bar:
                for split in self.split_bar:
                    split_vals = df[split].unique()
                    for index, split_val in enumerate(split_vals):
                        x = df[["n_samples", "n_features"]][df[split] == split_val]
                        x = [f"({ns}, {nf})" for ns, nf in x.values]
                        y = df["speedup"][df[split] == split_val]
                        bar = go.Bar(
                            x=x,
                            y=y,
                            name="%s: %s" % (split, split_val),
                            marker_color=px.colors.qualitative.Plotly[index],
                            hovertemplate=make_hover_template(
                                df[df[split] == split_val]
                            ),
                            customdata=df[df[split] == split_val].values,
                            showlegend=(row, col) == (1, 1),
                        )
                        fig.add_trace(
                            bar,
                            row=row,
                            col=col,
                        )
            else:
                x = df[["n_samples", "n_features"]]
                x = [f"({ns}, {nf})" for ns, nf in x.values]
                y = df["speedup"]
                bar = go.Bar(
                    x=x,
                    y=y,
                    hovertemplate=make_hover_template(df),
                    customdata=df.values,
                    showlegend=False,
                )
                fig.add_trace(
                    bar,
                    row=row,
                    col=col,
                )

        for i in range(1, n_plots + 1):
            fig["layout"]["xaxis{}".format(i)]["title"] = "(n_samples, n_features)"
            fig["layout"]["yaxis{}".format(i)]["title"] = "Speedup"

        fig.for_each_xaxis(
            lambda axis: axis.title.update(font=dict(size=REPORTING_FONT_SIZE))
        )
        fig.for_each_yaxis(
            lambda axis: axis.title.update(font=dict(size=REPORTING_FONT_SIZE))
        )
        fig.update_annotations(font_size=REPORTING_FONT_SIZE)
        fig.update_layout(
            height=n_rows * PLOT_HEIGHT_IN_PX, barmode="group", showlegend=True
        )
        fig.show()

    def run(self):
        display(Markdown(f"### Results"))
        self._print_table()
        display(Markdown(f"### Plots"))
        self._plot()
