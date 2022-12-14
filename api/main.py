import itertools
import os
from community import community_louvain
from flask import Flask, jsonify, request
from flask_cors import CORS
import gensim
import gensim.downloader
import networkx as nx
import nltk
from nltk.stem.wordnet import WordNetLemmatizer
from scipy.spatial.distance import pdist, squareform
from sklearn.neighbors import NearestNeighbors

app = Flask(__name__)
CORS(app)

model = gensim.downloader.load('word2vec-google-news-300')


def tokenize_en(text):
    stopwords = set(nltk.corpus.stopwords.words('english'))
    lemmatizer = WordNetLemmatizer()
    for token, pos in nltk.pos_tag(nltk.word_tokenize(text)):
        word = None
        if pos.startswith('NN'):
            word = lemmatizer.lemmatize(token, 'n')
        elif pos.startswith('JJ'):
            word = lemmatizer.lemmatize(token, 'a')
        elif pos.startswith('VB'):
            word = lemmatizer.lemmatize(token, 'v')
        if word and word not in stopwords:
            yield word


def count_words(words):
    word_count = {}
    for word in words:
        if word not in word_count:
            word_count[word] = 0
        word_count[word] += 1
    return word_count


def w2v_knn_graph_en(word_count, max_words, n_neighbors, distance_metric):
    words = sorted(
        [(word, count / model.get_vecattr(word, 'count'))
         for word, count in word_count.items() if word in model],
        key=lambda row: row[1], reverse=True)[:max_words]
    word_vectors = [model[word] for word, _ in words]
    distance_matrix = squareform(pdist(word_vectors, distance_metric))
    knn = NearestNeighbors(n_neighbors=n_neighbors,
                           algorithm='ball_tree').fit(word_vectors)
    knn_graph = knn.kneighbors_graph(word_vectors).toarray()

    graph = nx.Graph()
    indices = list(range(len(words)))
    for i, (word, weight) in zip(indices, words):
        graph.add_node(i, word=word, weight=weight)
    for i, j in itertools.combinations(indices, 2):
        if knn_graph[i, j]:
            graph.add_edge(i, j, weight=distance_matrix[i, j])
    return graph


def cluster_words(graph):
    dendrogram = community_louvain.generate_dendrogram(graph)
    dendrogram.append({k: 0 for k in set(dendrogram[-1].values())})
    data = []
    for i, layer in enumerate(dendrogram):
        for (k, v) in sorted(layer.items()):
            item = {
                'id': f'{i}-{k}',
                'parentId': f'{i + 1}-{v}',
            }
            if i == 0:
                item['word'] = graph.nodes[k]['word']
                item['weight'] = graph.nodes[k]['weight']
            data.append(item)
    data.append({
        'id': f'{len(dendrogram)}-0',
        'parentId': None
    })
    return data


@app.route("/knn_graph", methods=['POST'])
def knn_graph():
    text = request.data.decode()
    max_words = int(request.args.get('words', 100))
    n_neighbors = int(request.args.get('n_neighbors', 10))

    app.logger.info('start')
    word_count = count_words(tokenize_en(text))
    app.logger.info('tokenize')
    graph = w2v_knn_graph_en(word_count, max_words,
                             n_neighbors, distance_metric='cosine')
    app.logger.info('graph construction')
    data = cluster_words(graph)
    app.logger.info('clustering')

    return jsonify(data)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
