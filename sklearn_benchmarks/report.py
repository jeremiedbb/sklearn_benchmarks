import os
import importlib
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

    def _get_estimator_default_hyperparameters(self, estimator):
        splitted_path = estimator.split(".")
        module, class_name = ".".join(splitted_path[:-1]), splitted_path[-1]
        estimator_class = getattr(importlib.import_module(module), class_name)
        estimator_instance = estimator_class()
        hyperparameters = estimator_instance.__dict__.keys()
        return hyperparameters

    def _get_estimator_hyperparameters(self, estimator_config):
        if "hyperparameters" in estimator_config:
            return estimator_config["hyperparameters"].keys()
        else:
            return self._get_estimator_default_hyperparameters(
                estimator_config["estimator"]
            )

    def run(self):
        config = get_full_config(config_file_path=self.config_file_path)
        reporting_config = config["reporting"]
        benchmarking_estimators = config["benchmarking"]["estimators"]

        display(Markdown("## Time report"))
        self._print_time_report()

        reporting_estimators = reporting_config["estimators"]
        for name, params in reporting_estimators.items():
            params["n_cols"] = reporting_config["n_cols"]
            params["estimator_hyperparameters"] = self._get_estimator_hyperparameters(
                benchmarking_estimators[name]
            )
            display(Markdown(f"## {name} vs {params['against_lib']}"))
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
        compare=[],
        estimator_hyperparameters={},
        n_cols=None,
    ):
        self.name = name
        self.against_lib = against_lib
        self.split_bar = split_bar
        self.compare = compare
        self.n_cols = n_cols
        self.estimator_hyperparameters = estimator_hyperparameters

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

    def _make_plot_title(self, df):
        title = ""
        params_cols = [
            param
            for param in self.estimator_hyperparameters
            if param not in self.split_bar
        ]
        values = df[params_cols].values[0]
        for index, (param, value) in enumerate(zip(params_cols, values)):
            title += "%s: %s" % (param, value)
            if index > 0 and index % 3 == 0:
                title += "<br>"
            elif index != len(list(enumerate(zip(params_cols, values)))) - 1:
                title += " - "
        return title

    def _print_table(self):
        df = self._make_reporting_df()

        df["profiling"] = df[["hyperparams_digest", "dataset_digest"]].apply(
            self._make_profiling_link, axis=1
        )
        qgrid_widget = qgrid.show_grid(df, show_toolbar=True)
        display(qgrid_widget)

    def _make_x_plot(self, df):
        # df = df.sort_values(by=["function", "n_samples", "n_features"])
        return [f"({ns}, {nf})" for ns, nf in df[["n_samples", "n_features"]].values]

    def _plot(self):
        merged_df = self._make_reporting_df()
        if self.split_bar:
            group_by_params = [
                param
                for param in self.estimator_hyperparameters
                if param not in self.split_bar
            ]
            merged_df_grouped = merged_df.groupby(group_by_params)
        else:
            merged_df_grouped = merged_df.groupby("hyperparams_digest")

        n_plots = len(merged_df_grouped)
        n_rows = n_plots // self.n_cols + n_plots % self.n_cols
        coordinates = gen_coordinates_grid(n_rows, self.n_cols)

        subplot_titles = [self._make_plot_title(df) for _, df in merged_df_grouped]

        fig = make_subplots(
            rows=n_rows,
            cols=self.n_cols,
            subplot_titles=subplot_titles,
        )

        for (row, col), (_, df) in zip(coordinates, merged_df_grouped):
            df = df.sort_values(by=["function", "n_samples", "n_features"])
            df = df.dropna(axis="columns")

            if self.split_bar:
                for split_col in self.split_bar:
                    split_col_vals = df[split_col].unique()
                    for index, split_val in enumerate(split_col_vals):
                        x = df[df[split_col] == split_val][["n_samples", "n_features"]]
                        x = [f"({ns}, {nf})" for ns, nf in x.values]
                        y = df[df[split_col] == split_val]["speedup"]
                        bar = go.Bar(
                            x=x,
                            y=y,
                            name="%s: %s" % (split_col, split_val),
                            marker_color=px.colors.qualitative.Plotly[index],
                            hovertemplate=make_hover_template(
                                df[df[split_col] == split_val]
                            ),
                            customdata=df[df[split_col] == split_val].values,
                            showlegend=(row, col) == (1, 1),
                            text=df[df[split_col] == split_val]["function"],
                            textposition="auto",
                        )
                        fig.add_trace(
                            bar,
                            row=row,
                            col=col,
                        )
            else:
                n_samples_train_vals = df["n_samples_train"].unique()
                for index in range(len(n_samples_train_vals)):
                    n_sample_train_val = n_samples_train_vals[index]
                    x = self._make_x_plot(
                        df[df["n_samples_train"] == n_sample_train_val]
                    )
                    y = df[df["n_samples_train"] == n_sample_train_val]["speedup"]
                    bar = go.Bar(
                        x=x,
                        y=y,
                        name="%s: %s" % ("n_sample_train", n_sample_train_val),
                        hovertemplate=make_hover_template(
                            df[df["n_samples_train"] == n_sample_train_val]
                        ),
                        customdata=df[
                            df["n_samples_train"] == n_sample_train_val
                        ].values,
                        text=df[df["n_samples_train"] == n_sample_train_val][
                            "function"
                        ],
                        textposition="auto",
                        showlegend=(row, col) == (1, 1),
                        marker_color=px.colors.qualitative.Plotly[index],
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
