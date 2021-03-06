import tensorflow as tf
import numpy as np

from emoji_reader import emoji_64
from model_helpers import Embedding, xavier, build_bidirectional_rnn

class EmojiClassifier(object):
    def __init__(self,
                 batch_size,
                 vocab_size,
                 emoji_num,
                 embed_size,
                 num_unit,
                 num_gpu,
                 lr=0.001,
                 dropout=0.,
                 cell_type=tf.nn.rnn_cell.GRUCell
                 ):
        self.dropout = dropout
        self.num_gpu = num_gpu
        self.cell_type = cell_type

        self.text = tf.placeholder(tf.int32, shape=[None, batch_size], name="text")
        self.len = tf.placeholder(tf.int32, shape=[batch_size], name="text_length")
        self.emoji = tf.placeholder(tf.int32, shape=[batch_size], name="emoji_label")

        with tf.variable_scope("embeddings"):
            embedding = Embedding(vocab_size, embed_size)
            text_emb = embedding(self.text)

        with tf.variable_scope("bi_rnn_1"):  # difference between var scope and name scope?
            # tuple#2: [max_time, batch_size, num_unit]
            outputs_1, _ = build_bidirectional_rnn(
                num_unit, text_emb, self.len, cell_type, num_gpu, drop=dropout)

        with tf.variable_scope("bi_rnn_2"):
            rnn2_input = tf.concat([outputs_1[0], outputs_1[1]], axis=2)
            outputs_2, _ = build_bidirectional_rnn(
                num_unit, rnn2_input, self.len, cell_type, num_gpu, drop=dropout)

        with tf.variable_scope("attention"):
            word_states = tf.concat(
                [outputs_1[0], outputs_1[1], outputs_2[0], outputs_2[1], text_emb], axis=2)  # [max_t, b_sz, h_dim]

            weights = tf.layers.dense(word_states, 1, kernel_initializer=xavier)
            weights = tf.exp(weights)   # [max_len, batch_size, 1]

            # mask superfluous dimensions
            max_time = tf.shape(self.text)[0]
            weight_mask = tf.sequence_mask(self.len, max_time, dtype=tf.float32)
            weight_mask = tf.expand_dims(
                tf.transpose(weight_mask), axis=-1)  # transpose for time_major & expand to be broadcast-able
            weights = weights * weight_mask

            # weight regularization
            sums = tf.expand_dims(tf.reduce_sum(weights, axis=0), 0)  # [1, batch_size, 1]
            weights = weights / sums

            weights = tf.transpose(weights, [1, 0, 2])  # [batch_size, max_len, 1]
            word_states = tf.transpose(word_states, [1, 2, 0])  # [batch_size, h_dim, max_len]
            text_vec = tf.squeeze(tf.matmul(word_states, weights), axis=2)  # [batch_size, h_dim]

        with tf.variable_scope("loss"):
            logits = tf.layers.dense(text_vec, emoji_num, kernel_initializer=xavier)
            self.loss = tf.reduce_mean(
                tf.nn.sparse_softmax_cross_entropy_with_logits(labels=self.emoji, logits=logits))

        with tf.variable_scope("accuracy"):
            top_5_accuracy = tf.nn.in_top_k(logits, self.emoji, k=5)
            self.top_5_accuracy = tf.reduce_mean(tf.cast(top_5_accuracy, tf.float32))

            accuracy = tf.nn.in_top_k(logits, self.emoji, k=1)
            self.accuracy = tf.reduce_mean(tf.cast(accuracy, tf.float32))

        with tf.variable_scope("optimization"):
            optimizer = tf.train.AdamOptimizer(lr)
            self.update_step = optimizer.minimize(self.loss)

    def train_update(self, batch, sess):
        sess = sess or sess.get_default_session()
        text = batch[3]
        emoji_label = map_emoji(batch[0], emoji_index)
        length = batch[4]

        _, loss, accuracy, accuracy5 = sess.run(
            [self.update_step, self.loss, self.accuracy, self.top_5_accuracy],
            feed_dict={self.text: text, self.emoji: emoji_label, self.len: length})
        return loss, accuracy, accuracy5

    def eval(self, batches, sess):
        sess = sess or sess.get_default_session()
        loss_l = []
        accuracy_l = []
        accuracy5_l = []

        for batch in batches:
            text = batch[3]
            emoji_label = map_emoji(batch[0], emoji_index)
            length = batch[4]

            loss, accuracy, accuracy5 = sess.run(
                [self.loss, self.accuracy, self.top_5_accuracy],
                feed_dict={self.text: text, self.emoji: emoji_label, self.len: length})

            loss_l.append(loss)
            accuracy_l.append(accuracy)
            accuracy5_l.append(accuracy5)
        return float(np.mean(loss_l)), float(np.mean(accuracy_l)), float(np.mean(accuracy5_l))


batch_size = 128
# vocab_size =
emoji_num = 64
embed_size = 200
num_unit = 400
num_gpu = 2


def map_emoji(word_indices, emoji_index_dict):
    return np.array([emoji_index_dict[index] for index in word_indices])

if __name__ == '__main__':

    import argparse
    from time import gmtime, strftime
    from os import makedirs, chdir
    from os.path import join, dirname
    import json

    from helpers import build_vocab, build_data, build_emoji_index, batch_generator
    from helpers import print_out

    num_epoch = 3
    test_step = 50

    chdir("../data/full_64_input")
    output_dir = join("classify", strftime("%m-%d_%H-%M-%S", gmtime()))

    vocab_f = "vocab.ori"
    train_ori_f = "train.ori"
    train_rep_f = "train.rep"
    test_ori_f = "test.ori"
    test_rep_f = "test.rep"

    makedirs(dirname(join(output_dir, "breakpoints/")), exist_ok=True)
    log_f = open(join(output_dir, "log.txt"), "w")

    # build vocab
    word2index, index2word = build_vocab(vocab_f)
    start_i, end_i = word2index['<s>'], word2index['</s>']
    vocab_size = len(word2index)
    emoji_index = build_emoji_index(vocab_f, emoji_64)

    # building graph
    # embedding of discriminator's classifier should be in another graph
    classifier = EmojiClassifier(batch_size, vocab_size, emoji_num, embed_size, num_unit, num_gpu)

    # building data
    train_data = build_data(train_ori_f, train_rep_f, word2index)

    test_data = build_data(test_ori_f, test_rep_f, word2index)
    test_batches = batch_generator(
        test_data, start_i, end_i, batch_size, permutate=False)

    print_out("*** CLASSIFIER DATA READY ***")

    saver = tf.train.Saver()
    with tf.Session() as sess:
        best_f = join(output_dir, "best_accuracy.txt")

        global_step = best_step = 1
        start_epoch = best_epoch = 1
        best_loss = 1000.
        sess.run(tf.global_variables_initializer())
        # saver.restore(sess, "classify/08-09_21-30-45/breakpoints/best_test_loss.ckpt")
        for epoch in range(start_epoch, num_epoch + 1):
            train_batches = batch_generator(
                train_data, start_i, end_i, batch_size)

            loss_l = []
            accuracy_l = []
            accuracy5_l = []
            for batch in train_batches:
                loss, accuracy, accuracy5 = classifier.train_update(batch, sess)
                loss_l.append(loss)
                accuracy_l.append(accuracy)
                accuracy5_l.append(accuracy5)

                if global_step % test_step == 0:
                    time_now = strftime("%m-%d %H:%M:%S", gmtime())
                    print_out('epoch:\t%d\tstep:\t%d\tbatch-loss/accuracy/accuracy5:\t%.3f\t%.1f\t%.1f\t\t%s' %
                              (epoch, global_step,
                               np.mean(loss_l), np.mean(accuracy_l) * 100, np.mean(accuracy5_l) * 100, time_now),
                              f=log_f)
                if global_step % (test_step * 10) == 0:
                    loss, accuracy, accuracy5 = classifier.eval(test_batches, sess)
                    print_out('EPOCH-\t%d\tSTEP-\t%d\tTEST-loss/accuracy/accuracy5-\t%.3f\t%.1f\t%.1f' %
                              (epoch, global_step,
                               loss, accuracy * 100, accuracy5 * 100),
                              f=log_f)

                    if best_loss >= loss:
                        best_loss = loss

                        best_epoch = epoch
                        best_step = global_step

                        # save breakpoint
                        path = join(output_dir, "breakpoints/best_test_loss.ckpt")
                        save_path = saver.save(sess, path)

                        # save best epoch/step
                        best_dict = {
                            "loss": best_loss, "epoch": best_epoch, "step": best_step, "accuracy": accuracy,
                            "top_5_accuracy": accuracy5}
                        with open(path, "w") as f:
                            f.write(json.dumps(best_dict, indent=2))
                global_step += 1

            loss, accuracy, accuracy5 = classifier.eval(train_batches, sess)
            print_out('EPOCH!\t%d\tTRAIN!\t%d\tTRAIN-loss/accuracy/accuracy5-\t%.3f\t%.1f\t%.1f' %
                      (epoch, global_step,
                       np.mean(loss_l), np.mean(accuracy_l) * 100, np.mean(accuracy5_l) * 100),
                      f=log_f)

    log_f.close()
