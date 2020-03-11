import torch
import torch.nn as nn
import torch.nn.init as init


class WordLSTMCore(nn.Module):
    def __init__(self, input_size, n_lstm_layers, hidden_size, dropout):
        super(WordLSTMCore, self).__init__()

        self.hidden_size = hidden_size
        self.n_lstm_layers = n_lstm_layers

        self.bilstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=n_lstm_layers,
            dropout=dropout if n_lstm_layers > 1 else 0,
            bidirectional=True,
            batch_first=True)
        self.linear = nn.Linear(
            in_features=hidden_size*2,
            out_features=self.output_size())

    # TODO what size is this really?
    def output_size(self):
        return self.hidden_size

    def initialise(self):
        # TODO this is not documented in the paper
        # TODO initialise bilstm weights
        init.normal_(self.linear.weight)

    def forward(self, x):
        lstm_out, _ = self.bilstm(
            x.unsqueeze(dim=1)
        )
        lstm_out = lstm_out.squeeze(dim=1)

        # TODO residual instead of paper
        lstm_out += torch.cat([x, x], dim=1)

        linear_out = self.linear(lstm_out)
        return linear_out

    def log_tensorboard(self, writer, name, iteration_counter):
        for a in ['bias', 'weight']:
            for b in ['ih', 'hh']:
                for direction in ['', '_reverse']:
                    for i in range(self.n_lstm_layers):
                        writer.add_histogram(
                            #  f'bilstm/{a}/{b}_{i}_{direction}/gradients',
                            f'grads/{name}/bilstm_combined',
                            getattr(self.bilstm, f'{a}_{b}_l{i}{direction}').grad,
                            iteration_counter
                        )
        writer.add_histogram(
            f'grads/{name}/linear',
            self.linear.weight.grad,
            iteration_counter
        )


class CharLSTMCore(nn.Module):
    def __init__(self, input_size, n_lstm_layers, hidden_size, dropout, debug=False):
        super(CharLSTMCore, self).__init__()

        self.hidden_size = hidden_size
        self.n_lstm_layers = n_lstm_layers

        self.bilstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=n_lstm_layers,
            dropout=dropout if n_lstm_layers > 1 else 0,
            bidirectional=True,
            batch_first=True)
        self.linear = nn.Linear(
            in_features=hidden_size*4,
            out_features=self.output_size())
        self.debug = debug

    # TODO what size is this really?
    def output_size(self):
        return self.hidden_size

    def initialise(self):
        # TODO init bilstm_weights
        init.normal_(self.linear.weight)

    def forward(self, x, firsts, lasts):
        if self.debug:
            print(
                f'input {x.size()}\n'
                # f'{x}\n'
                f'firsts {firsts.size()}\n'
                # f'{firsts}\n'
                f'lasts {lasts.size()}\n'
                # f'{lasts}'
            )
        lstm_out, _ = self.bilstm(
            x.unsqueeze(dim=1)
        )
        lstm_out = lstm_out.squeeze(dim=1)
        if self.debug:
            print(
                f'lstm_out {lstm_out.size()}\n'
                # f'{lstm_out}'
            )

        # TODO this is residual, other than paper
        lstm_out += torch.cat([x, x], dim=1)

        catted = torch.cat(
            [lstm_out[firsts], lstm_out[lasts]],
            dim=1
        )
        if self.debug:
            print(
                f'catted {catted.size()}\n'
                # f'{catted}'
            )
        # TODO this is definitely the wrong shape
        linear_out = self.linear(catted)
        if self.debug:
            print(
                f'output {linear_out.size()}\n'
                # f'{x}'
            )
        return linear_out

    def log_tensorboard(self, writer, name, iteration_counter):
        for a in ['bias', 'weight']:
            for b in ['ih', 'hh']:
                for direction in ['', '_reverse']:
                    for i in range(self.n_lstm_layers):
                        writer.add_histogram(
                            #  f'bilstm/{a}/{b}_{i}_{direction}/gradients',
                            f'grads/{name}/bilstm_combined',
                            getattr(self.bilstm, f'{a}_{b}_l{i}{direction}').grad,
                            iteration_counter
                        )
        writer.add_histogram(
            f'grads/{name}/linear',
            self.linear.weight.grad,
            iteration_counter
        )
