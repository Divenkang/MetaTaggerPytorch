from build_dicts import load_converted_data, convert_data
from Lexicon import LabeledData, get_labeled_data_path
import json
import torch
from LSTMModel import LSTMModel


def run_complete_net(debug=False):
    dataset = 'conll17'
    tag_name = 'POS'
    epochs = 1

    with open('data.json', 'r') as file:
        data = json.load(file)
    
    for language in ['de']:  # data[dataset]['languages']:
        labels = LabeledData.load(
            get_labeled_data_path(
                dataset=dataset,
                language=language
            )
        )
        sentences = load_converted_data(
            language=language,
            dataset=dataset
        )

        n_tags = len(labels.tags[tag_name])
        embedding_dim = 3

        model = LSTMModel(
            n_chars=labels.lexicon.n_chars(),
            n_words=labels.lexicon.n_words(),
            n_tags=n_tags,
            embedding_dim=embedding_dim,
            cuda=False,
            debug=debug
        )

        model.initialise()

        word_list = labels.lexicon._words.to_dict()['elements']
        # TODO rename blubb to unknown
        word_list_unk = ['blubb'] + word_list
        model.run_training(
            sentences=sentences,
            epochs=epochs,
            tag_name=tag_name,
            n_tags=n_tags,
            word_list=word_list_unk
        )

        print('training finished, starting evaluation')

        scores = model.dev_eval(
            tag_name=tag_name,
            path='Corpora/ud_test_v2_0_conll2017/gold/conll17-ud-test-2017-05-09/de.conllu',
            labeled_data=labels
        )

        for category in scores:
            print(category)
            print(scores[category].precision)
            print(scores[category].recall)
            print(scores[category].f1)

        torch.save(
            model.get_state_dicts(
                language=language,
                dataset=dataset
            ), 
            f'Models/conll17/{language}'
        )


if __name__ == "__main__":
    # convert_data()
    run_complete_net(debug=False)
