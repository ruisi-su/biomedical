import sys
from datasets import load_dataset
import streamlit as st
import time
import numpy as np
import plotly.figure_factory as ff
import plotly.graph_objects as go
from rich import print as rprint

import plotly.express as px
import pandas as pd

from bigbio.dataloader import BigBioConfigHelpers
from collections import defaultdict, OrderedDict, Counter


# vanilla tokenizer
def tokenizer(text):
    if not text:
        return text, []
    text = text.strip()
    text = text.replace("\t", "")
    text = text.replace("\n", "")
    # split
    text_list = text.split(" ")
    return text, text_list


def norm(lengths):
    mu = np.mean(lengths)
    sigma = np.std(lengths)
    return mu, sigma


def load_helper():
    conhelps = BigBioConfigHelpers()
    conhelps = conhelps.filtered(lambda x: x.dataset_name != "pubtator_central")
    conhelps = conhelps.filtered(lambda x: x.is_bigbio_schema)
    conhelps = conhelps.filtered(lambda x: not x.is_local)
    rprint(
        "loaded {} configs from {} datasets".format(
            len(conhelps),
            len(set([helper.dataset_name for helper in conhelps])),
        )
    )
    return conhelps


_TEXT_MAPS = {
    "bigbio_kb": ["text"],
    "bigbio_text": ["text"],
    "bigbio_qa": ["question", "context"],
    "bigbio_te": ["premise", "hypothesis"],
    "bigbio_tp": ["text_1", "text_2"],
    "bigbio_pairs": ["text_1", "text_2"],
    "bigbio_t2t": ["text_1", "text_2"],
}

IBM_COLORS = [
    "#648fff",
    "#dc267f",
    "#ffb000",
    "#fe6100",
    "#785ef0",
    "#000000",
    "#ffffff",
]


def token_length_per_entry(entry, schema):
    result = {}
    if schema == "bigbio_kb":
        for passage in entry["passages"]:
            result_key = passage['type']
            for key in _TEXT_MAPS[schema]:
                text = passage[key][0]
                _, toks = tokenizer(text)
                result[result_key] = len(toks)

    else:
        for key in _TEXT_MAPS[schema]:
            text = entry[key]
            _, toks = tokenizer(text)
            result[key] = len(toks)
    return result


def parse_token_length(dataset, data_config, st=None):
    hist_data = []
    rprint(data_config)
    for split, data in dataset.items():
        my_bar = st.progress(0)
        total = len(data)
        for i, entry in enumerate(data):
            my_bar.progress(int(i / total * 100))
            result = token_length_per_entry(entry, data_config.schema)
            result['total_token_length'] = sum([v for k, v in result.items()])
            result["split"] = split
            hist_data.append(result)
        my_bar.empty()
    st.write('token lengths complete!')
    return pd.DataFrame(hist_data)


def draw_histogram(hist_data, col_name, st=None):
    fig = px.histogram(
        hist_data,
        x=col_name,
        color="split",
        color_discrete_sequence=IBM_COLORS,
        marginal="box",  # or violin, rug
        barmode="group",
        hover_data=hist_data.columns,
        histnorm='probability',
        nbins=20,
    )
    st.plotly_chart(fig, use_container_width=True)


def draw_bar(bar_data, x, y, st=None):
    fig = px.bar(
        bar_data,
        x=x,
        y=y,
        color="split",
        color_discrete_sequence=IBM_COLORS,
        # marginal="box",  # or violin, rug
        barmode="group",
        hover_data=bar_data.columns,
    )
    st.plotly_chart(fig, use_container_width=True)


def parse_metrics(metadata, st=None):
    for k, m in metadata.items():
        mattrs = m.__dict__
        for m, attr in mattrs.items():
            if type(attr) == int and attr > 0:
                st.metric(label=f'{k}-{m}', value=attr)


def parse_counters(metadata):
    metadata = metadata['train']  # using the training counter to fetch the names
    counters = []
    for k, v in metadata.__dict__.items():
        if 'counter' in k and len(v) > 0:
            counters.append(k)
    return counters


# generate the df for histogram
def parse_label_counter(metadata, counter_type):
    hist_data = []
    for split, m in metadata.items():
        metadata_counter = getattr(m, counter_type)
        for k, v in metadata_counter.items():
            row = {}
            row["labels"] = k
            row[counter_type] = v
            row['split'] = split
            hist_data.append(row)
    return pd.DataFrame(hist_data)


if __name__ == "__main__":
    # load helpers
    conhelps = load_helper()
    configs_set = set()

    for conhelper in conhelps:
        configs_set.add(conhelper.dataset_name)

    # setup page, sidebar, columns
    st.set_page_config(layout="wide")
    s = st.session_state
    if not s:
        s.pressed_first_button = False
    data_name = st.sidebar.selectbox("dataset", configs_set)
    st.sidebar.write("you selected:", data_name)
    st.header(f"Dataset stats for {data_name}")

    # setup data configs
    data_helpers = conhelps.for_dataset(data_name)
    data_configs = [d.config for d in data_helpers]
    data_config_names = [d.config.name for d in data_helpers]
    data_config_name = st.sidebar.selectbox("config", set(data_config_names))

    if st.sidebar.button("fetch") or s.pressed_first_button:
        s.pressed_first_button = True
        helper = conhelps.for_config_name(data_config_name)
        metadata_helper = helper.get_metadata()

        parse_metrics(metadata_helper, st.sidebar)

        # load HF dataset
        data_idx = data_config_names.index(data_config_name)
        data_config = data_configs[data_idx]
        dataset = load_dataset(
            f"bigbio/biodatasets/{data_name}/{data_name}.py", name=data_config_name)
        # general token length
        tok_hist_data = parse_token_length(dataset, data_config, st.sidebar)

        # draw token distribution
        draw_histogram(tok_hist_data, "total_token_length", st)
        # general counter(s)
        col1, col2 = st.columns([1, 6])
        counters = parse_counters(metadata_helper)
        counter_type = col1.selectbox("counter_type", counters)
        label_df = parse_label_counter(metadata_helper, counter_type)
        label_max = int(label_df[counter_type].max())
        label_min = int(label_df[counter_type].min())
        filter_value = col1.slider('counter_filter (min, max)', label_min, label_max)
        label_df = label_df[label_df[counter_type] >= filter_value]
        # draw bar chart for counter
        draw_bar(label_df, "labels", counter_type, col2)
        # emb_df = main()
        # emb_fig = px.scatter_3d(emb_df, x='x', y='y', z='z', color='sent')
        # st.plotly_chart(emb_fig, use_container_width=True)

    st.sidebar.button("Re-run")
