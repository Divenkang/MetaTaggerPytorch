from build_dicts import ID, FORM, tag_name_to_column
from Classifier import Classifier
from core import WordLSTMCore, CharLSTMCore
from Corpora.ud_test_v2_0_conll2017.evaluation_script.conll17_ud_eval import evaluate, load_conllu_file
from itertools import chain
import torch
import torch.nn as nn
import torch.nn.init as init
from tensorboard_logging import log_log_histogram


class BatchContainer:
    def __init__(self, chars, words, tags, firsts, lasts):
        self.chars = chars
        self.words = words
        self.tags = tags
        self.firsts = firsts
        self.lasts = lasts


class LSTMModel(nn.Module):
    def __init__(self, n_chars, n_words, n_tags, embedding_dim, residual, cuda, debug=False):
        super(LSTMModel, self).__init__()

        self.debug = debug

        self.residual = residual

        self.char_id_dropout = nn.Dropout(p=0.05)
        self.word_id_dropout = nn.Dropout(p=0.05)

        self.char_embedding = nn.Embedding(
            num_embeddings=n_chars,
            embedding_dim=embedding_dim)
        self.word_embedding = nn.Embedding(
            num_embeddings=n_words,
            embedding_dim=embedding_dim)

        self.embedding_normalise = nn.Softmax(dim=2)

        self.char_embedding_dropout = nn.Dropout(p=0.05)
        self.word_embedding_dropout = nn.Dropout(p=0.05)

        self.char_core = CharLSTMCore(
            input_size=embedding_dim,
            n_lstm_layers=3,
            hidden_size=embedding_dim,
            dropout=0.05,  # 0.33,
            debug=debug,
            residual=residual
        )
        self.word_core = WordLSTMCore(
            input_size=embedding_dim,
            n_lstm_layers=3,
            hidden_size=embedding_dim,
            dropout=0.05,  # 0.33,
            residual=residual
        )
        self.meta_core = WordLSTMCore(
            input_size=embedding_dim * 2,
            n_lstm_layers=1,
            hidden_size=embedding_dim * 2,
            dropout=0.05,  # 0.33,
            residual=residual
        )

        self.char_classifier = Classifier(
            input_size=embedding_dim,
            n_tags=n_tags)
        self.word_classifier = Classifier(
            input_size=embedding_dim,
            n_tags=n_tags)
        self.meta_classifier = Classifier(
            input_size=embedding_dim * 2,
            n_tags=n_tags)

        if cuda:
            self.device = torch.device('cuda')
            self.apply(lambda m: m.cuda())
        else:
            self.device = torch.device('cpu')

    def initialise(self):
        print('initialise LSTMModel')
        init.uniform_(self.char_embedding.weight)
        init.uniform_(self.word_embedding.weight)

        self.char_core.initialise()
        self.word_core.initialise()
        self.meta_core.initialise()

    def forward(self, inputs):
        '''
        char_embeddings = self.embedding_normalise(
            self.char_embedding_dropout(
                self.char_embedding(char_ids)
            )
        )
        word_embeddings = self.embedding_normalise(
            self.word_embedding_dropout(
                self.word_embedding(word_ids)
            )
        )
        '''
        # TODO id dropout sets some words to 'unknown'; further, the embedding for 'unknown' is used and trained
        # char_ids = self.char_id_dropout(inputs[0])
        # word_ids = self.word_id_dropout(inputs[1])

        char_ids = inputs[0]
        word_ids = inputs[1]

        first_ids = inputs[2]
        last_ids = inputs[3]

        char_embeddings = self.char_embedding(char_ids)
        word_embeddings = self.word_embedding(word_ids)

        char_dropout_embeddings = self.char_embedding_dropout(char_embeddings)
        word_dropout_embeddings = self.word_embedding_dropout(word_embeddings)

        # TODO hack, dropout skipped
        char_core_out = self.char_core(char_dropout_embeddings, first_ids, last_ids)
        word_core_out = self.word_core(word_dropout_embeddings)

        with torch.no_grad():
            catted = torch.cat(
                (
                    char_core_out,
                    word_core_out
                ),
                dim=1
            )
        meta_core_out = self.meta_core(catted)

        char_probs = self.char_classifier(char_core_out)
        word_probs = self.word_classifier(word_core_out)
        meta_probs = self.meta_classifier(meta_core_out)

        return char_probs, word_probs, meta_probs

    # sentence must separate words and punctuation by spaces
    # e.g.: 'Ich verstehe , dass man die Lücken normalerweise nicht lässt .'
    def tag_sentence(self, sentence):
        chars, words, firsts, lasts = [], [], [], []
        i = 0
        for word in sentence.split():
            chars.extend(word)
            chars.append(' ')
            words.append(word)
            firsts.append(i)
            i + len(word)
            lasts.append(i-1)
        chars = torch.tensor([chars[:-1]], dtype=torch.long, device=self.device)
        words = torch.tensor([words], dtype=torch.long, device=self.device)
        firsts = torch.tensor(firsts, dtype=torch.long, device=self.device)
        lasts = torch.tensor(lasts, dtype=torch.long, device=self.device)
        return [
            self.tags.get_value(index=tag_index)
            for tag_index
            in self.predict(chars, words, firsts, lasts)
        ]

    def get_char_params(self):
        return chain(
            self.char_embedding.parameters(),
            self.char_core.parameters(),
            self.char_classifier.parameters()
        )

    def get_word_params(self):
        return chain(
            self.word_embedding.parameters(),
            self.word_core.parameters(),
            self.word_classifier.parameters()
        )

    def get_meta_params(self):
        return chain(
            self.meta_core.parameters(),
            self.meta_classifier.parameters()
        )

    def get_state_dicts(self, language, dataset):
        return {
            'model': self.state_dict(),
            'char_optimizer': self.char_optimizer.state_dict(),
            'word_optimizer': self.word_optimizer.state_dict(),
            'meta_optimizer': self.meta_optimizer.state_dict(),
            'language': language,
            'dataset': dataset
        }

    # TODO write construction parameters, make static constructor from path
    def load_state_dicts(self, dicts, load_optimizers=True):
        self.load_state_dict(dicts['model'])
        if load_optimizers:
            self.char_optimizer.load_state_dict(dicts['char_optimizer'])
            self.word_optimizer.load_state_dict(dicts['word_optimizer'])
            self.meta_optimizer.load_state_dict(dicts['meta_optimizer'])

    def dev_eval(self, tag_name, path, labeled_data):
        self.eval()

        work_data = load_conllu_file(path)
        words_count = len(work_data.tokens)

        tag_column_id = tag_name_to_column(tag_name=tag_name)

        print(f'words: {words_count}')

        # TODO make a function ouf of this that is also called in build_dicts
        start_id = 0
        while start_id < words_count:
            end_id = start_id + 1
            while end_id < words_count and work_data.words[end_id].columns[ID] != '1':
                end_id += 1

            # print(start_id, end_id)

            char_ids = []
            word_ids = []
            first_ids = []
            last_ids = []
            char_pos = 0

            # end_word_id stops on first token of next sentence
            for token in work_data.words[start_id: end_id]:
                token_chars = [
                    labeled_data.lexicon.get_char(char)
                    for char
                    in work_data.characters[token.span.start: token.span.end]
                ]
                char_ids.extend(token_chars)
                char_ids.append(labeled_data.lexicon.get_char(' '))
                first_ids.append(char_pos)
                char_pos += len(token_chars)
                last_ids.append(char_pos - 1)
                # add one for space between words
                char_pos += 1
                word_ids.append(
                    labeled_data.lexicon.get_word(token.columns[FORM])
                )

            _, _, probabilities = self.forward([
                torch.tensor(char_ids, dtype=torch.long, device=self.device),
                torch.tensor(word_ids, dtype=torch.long, device=self.device),
                torch.tensor(last_ids, dtype=torch.long, device=self.device),
                torch.tensor(first_ids, dtype=torch.long, device=self.device),
            ])

            # TODO zip Tensor? make this better
            for tag_id, token in zip(
                    probabilities.argmax(dim=1),
                    work_data.words[start_id: end_id]
            ):
                token.columns[tag_column_id] = labeled_data.tags[tag_name].get_value(tag_id)
                print(token.columns)

            start_id = end_id

        gold_data = load_conllu_file(path)
        scores = evaluate(gold_data, work_data)

        # TODO maybe unpack this foreign scores
        return scores

    def log_char_net(self, writer, steps):
        log_log_histogram(
            writer=writer,
            steps=steps,
            name='grads/char_embedding',
            tensor=self.char_embedding.weight.grad
        )
        log_log_histogram(
            writer=writer,
            steps=steps,
            name='weights/char_embedding',
            tensor=self.char_embedding.weight,
        )
        self.char_core.log_tensorboard(
            writer=writer,
            name='char_core/',
            iteration_counter=steps
        )
        self.char_classifier.log_tensorboard(
            writer=writer,
            name='char_classifier/',
            iteration_counter=steps
        )

    def log_word_net(self, writer, steps):
        log_log_histogram(
            writer=writer,
            steps=steps,
            name='grads/word_embedding',
            tensor=self.word_embedding.weight.grad,
        )
        log_log_histogram(
            writer=writer,
            steps=steps,
            name='weights/word_embedding',
            tensor=self.word_embedding.weight,
        )
        self.word_core.log_tensorboard(
            writer=writer,
            name='word_core/',
            iteration_counter=steps
        )
        self.word_classifier.log_tensorboard(
            writer=writer,
            name='word_classifier/',
            iteration_counter=steps
        )

    def log_meta_net(self, writer, steps):
        self.meta_core.log_tensorboard(
            writer=writer,
            name='meta_core/',
            iteration_counter=steps
        )
        self.meta_classifier.log_tensorboard(
            writer=writer,
            name='meta_classifier/',
            iteration_counter=steps
        )

    def log_embeddings(self, writer, steps, word_list, char_list):
        print('save embeddings')
        writer.add_embedding(
            self.word_embedding.weight,
            global_step=steps,
            tag=f'word_embeddings{steps}',
            metadata=word_list
        )
        writer.add_embedding(
            self.char_embedding.weight,
            global_step=steps,
            tag=f'char_embeddings{steps}',
            metadata=char_list
        )

    # TODO complete this
    def algorithm_1(self, train_data):
        self.initialze()
        epochs = 10

        best_f1 = 0

        for _ in range(epochs):
            char_logits, char_preds = self.run_char_model(train_data)
            self.char_optimizer.step()
            word_logits, word_preds = self.run_word_model(train_data)
            self.word_optimizer.step()
            meta_logits, meta_preds = self.run_meta_model(train_data)
            self.meta_optimizer.step()

            # TODO this returns much more than just a number right now. check!
            f1 = self.dev_eval()
            if f1 > best_f1:
                # implement this
                self.lock_best_model()
                best_f1 = f1
