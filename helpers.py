import numpy as np
import random
import tensorflow as tf
tf.logging.set_verbosity(tf.logging.DEBUG)
import math
import sys
from time import gmtime, strftime

"""build data"""
def build_emoji_index(vocab_path, emoji_list):
    vocab_file = open(vocab_path, encoding="utf-8")
    vocab_data = vocab_file.readlines()
    vocab_file.close()

    i = 0
    emoji_index = {}
    for index, line in enumerate(vocab_data):
        word = line.rstrip()
        if word in emoji_list:
            emoji_index[index] = i
            i += 1
    assert i == 64
    return emoji_index

def build_vocab(vocab_path):
    vocab_file = open(vocab_path, encoding="utf-8")
    vocab_data = vocab_file.readlines()
    vocab_file.close()

    index2word = dict()
    word2index = dict()
    for index, line in enumerate(vocab_data):
        word = line.rstrip()
        index2word[index] = word
        word2index[word] = index
    return word2index, index2word

def build_data(ori_path, rep_path, word2index):
    unk_i = word2index['<unk>']

    ori_file = open(ori_path, encoding="utf-8")
    ori_tweets = ori_file.readlines()
    ori_file.close()

    rep_file = open(rep_path, encoding="utf-8")
    rep_tweets = rep_file.readlines()
    rep_file.close()

    assert(len(ori_tweets) == len(rep_tweets))
    emojis = []
    ori_seqs = []
    rep_seqs = []

    for i in range(len(ori_tweets)):
        ori_words = ori_tweets[i].split()
        ori_tweet = [word2index.get(word, unk_i) for word in ori_words[1:]]

        rep_words = rep_tweets[i].split()
        rep_tweet = [word2index.get(word, unk_i) for word in rep_words]

        if len(ori_tweet) < 3 or len(rep_tweet) < 2:
            continue

        ori_seqs.append(ori_tweet)
        rep_seqs.append(rep_tweet)
        emojis.append(word2index.get(ori_words[0], unk_i))

    return [
        emojis,
        ori_seqs,
        rep_seqs
    ]

def generate_one_batch(data_l, start_i, end_i, s, e):
    emojis = data_l[0]
    ori_seqs = data_l[1]
    rep_seqs = data_l[2]

    if e is None:
        e = len(emojis)

    emoji_vec = np.array(emojis[s:e], dtype=np.int32)

    ori_lengths = np.array([len(seq) for seq in ori_seqs[s:e]])
    max_ori_len = np.max(ori_lengths)
    min_ori_len = np.min(ori_lengths)
    assert(min_ori_len > 0)
    ori_matrix = np.zeros([max_ori_len, e - s], dtype=np.int32)

    for i, seq in enumerate(ori_seqs[s:e]):
        for j, elem in enumerate(seq):
            ori_matrix[j, i] = elem

    rep_lengths = np.array([len(seq) for seq in rep_seqs[s:e]])
    max_rep_len = np.max(rep_lengths)
    rep_matrix = np.zeros([max_rep_len, e - s], dtype=np.int32)
    rep_input_matrix = np.zeros([max_rep_len + 1, e - s], dtype=np.int32)
    rep_output_matrix = np.zeros([max_rep_len + 1, e - s], dtype=np.int32)

    rep_input_matrix[0, :] = start_i
    for i, seq in enumerate(rep_seqs[s:e]):
        for j, elem in enumerate(seq):
            rep_matrix[j, i] = elem
            rep_input_matrix[j + 1, i] = elem
            rep_output_matrix[j, i] = elem
        rep_output_matrix[len(seq), i] = end_i

    return [
            emoji_vec,
            ori_matrix,
            ori_lengths,
            rep_matrix,
            rep_lengths,
            rep_input_matrix,
            rep_output_matrix
    ]

def batch_generator(data_l, start_i, end_i, batch_size, permutate=True):
    # shuffle
    emojis = data_l[0]
    ori_seqs = data_l[1]
    rep_seqs = data_l[2]

    if permutate:
        all_input = list(zip(emojis, ori_seqs, rep_seqs))

        random.shuffle(all_input)
        new_all = list(zip(*all_input))
    else:
        new_all = [emojis, ori_seqs, rep_seqs]

    data_size = len(emojis)
    num_batches = int((data_size - 1.) / batch_size) + 1

    rtn = []
    for batch_num in range(num_batches):
        e = min((batch_num + 1) * batch_size, data_size)
        s = e - batch_size
        assert(s >= 0)
        rtn.append(generate_one_batch(new_all, start_i, end_i, s, e))
    return rtn

# for discriminator
def build_dis_data(human_path, machine_path, word2index):
    unk_i = word2index['<unk>']

    with open(human_path, encoding="utf-8") as f:
        human_tweets = f.readlines()

    with open(machine_path, encoding="utf-8") as f:
        machine_tweets = f.readlines()

    seqs = []
    for i in range(len(human_tweets)):
        words = human_tweets[i].split()
        tweet = [word2index.get(word, unk_i) for word in words]
        if len(tweet) < 3:
            continue
        seqs.append(tweet)
    labels = [0] * len(seqs)
    for i in range(len(machine_tweets)):
        words = machine_tweets[i].split()
        tweet = [word2index.get(word, unk_i) for word in words]
        if len(tweet) < 3:
            continue
        seqs.append(tweet)
    labels += [1] * (len(seqs)-len(labels))

    assert len(labels) == len(seqs)
    return [seqs, labels]

def generate_dis_batches(data_l, batch_size, permutate):
    seqs = data_l[0]
    labels = data_l[1]

    if permutate:
        all_input = list(zip(seqs, labels))

        random.shuffle(all_input)
        seqs, labels = list(zip(*all_input))

    data_size = len(labels)
    num_batches = int((data_size - 1.) / batch_size) + 1

    batches = []
    for batch_num in range(num_batches):
        e = min((batch_num + 1) * batch_size, data_size)
        s = e - batch_size
        assert (s >= 0)

        labels_vec = np.array(labels[s:e], dtype=np.int32)

        text_lengths = np.array([len(seq) for seq in seqs[s:e]])
        max_text_len = np.max(text_lengths)
        min_text_len = np.min(text_lengths)
        assert (min_text_len > 0)
        text_matrix = np.zeros([max_text_len, batch_size], dtype=np.int32)

        for i, seq in enumerate(seqs[s:e]):
            for j, elem in enumerate(seq):
                text_matrix[j, i] = elem

        one_batch = [text_matrix, text_lengths, labels_vec]
        batches.append(one_batch)
    return batches

"""utils"""
def safe_exp(value):
  """Exponentiation with catching of overflow error."""
  try:
    ans = math.exp(value)
  except OverflowError:
    ans = float("inf")
  return ans

def generate_graph():
    graph_def = tf.get_default_graph().as_graph_def()
    graphpb_txt = str(graph_def)
    with open('miscellanies/graphpb.txt', 'w') as f:
        f.write(graphpb_txt)
    exit(0)

class Printer(object):
    def __init__(self, f):
        self.log_f = f

    def __call__(self, s, new_line=True):
        now = strftime("%m-%d %H:%M:%S", gmtime())
        s += "\t\t" + now
        self.log_f.write(s)
        if new_line:
            self.log_f.write("\n")
        self.log_f.flush()

        # stdout
        print(s, end="", file=sys.stdout)
        if new_line:
            sys.stdout.write("\n")
        sys.stdout.flush()

    def put_eval(self, recon_loss, kl_loss, bow_loss, ppl, bleu_score, precisions_list, name):
        self("%s: " % name, new_line=False, f=self.log_f)
        format_string = '\trecon/kl/bow-loss/ppl:\t%.3f\t%.3f\t%.3f\t%.3f\tBLEU:' + '\t%.1f' * 5
        format_tuple = (recon_loss, kl_loss, bow_loss, ppl, bleu_score) + tuple(precisions_list)
        self(format_string % format_tuple, f=self.log_f)

def print_out(s, f=None, new_line=True):
  """Similar to print but with support to flush and output to a file."""
  if f:
    f.write(s)
    if new_line:
      f.write("\n")
    f.flush()

  # stdout
  print(s, end="", file=sys.stdout)
  if new_line:
    sys.stdout.write("\n")
  sys.stdout.flush()

def selu(z,
         scale=1.0507009873554804934193349852946,
         alpha=1.6732632423543772848170429916717):
    return scale * tf.where(z >= 0.0, z, alpha * tf.nn.elu(z))
