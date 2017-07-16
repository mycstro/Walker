# tensorboard --logdir=cbioDavid projects/Walker/dqn/summary

# Progs/ython/python cbioDavid/projects/Walker/reinfLearn.py
# tensorboard --logdir=C:\Users\booga\Dropbox\bio\projects\Walker\dqn\summary
# python C:\Users\booga\Dropbox\bio\projects\Walker\reinfLearn.py
import numpy as np
import os
import sys
import time
import traceback
import tensorflow as tf
from Walker import Walker
from QNetwork import QNetwork
from ExperienceBuffer import ExperienceBuffer
# import random
# import matplotlib.pyplot as plt
# from multiprocessing import Process

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

BATCH_SIZE = 10  # How many experiences to use for each training step.
DISCOUNT = .99  # Discount factor on the target Q-values
START_EXPLOIT_PROB = 1  # Starting chance of random action
END_EXPLOIT_PROB = 0.2  # Final chance of random action
NUM_EPISODES = 200000  # How many episodes of game environment to train network with.
ANNEALING_STEPS = 15000  # How many steps of training to reduce START_EXPLOIT_PROB to END_EXPLOIT_PROB.
PRE_TRAIN_STEPS = 500  # How many steps of random actions before training begins.
STEPS_IN_PACE = 10  # steps in a pace
MAX_PACES_IN_EPISODE = 10  # The max allowed paces in an episode
BASE_DIR = os.path.join(os.path.dirname(sys.argv[0]), "dqn")  # The path to save our model to.
SUMMARY_BASE_DIR = os.path.join(BASE_DIR, 'summary')
TAU = 0.001  # Rate to update target network toward primary network
EPISODES_BETWEEN_SAVE = 10000
EPISODES_BETWEEN_BIG_SUMMERY = 10
STOP_EPISODE_SCORE_THRESHOLD = -3
STOP_EPISODE_STATE_THRESHOLD = 0.0001
POST_EPISODE_TRAINS = 30


class Learner(object):
    def _count_subdirs(self, base_dir):
        count = 0
        if not os.path.exists(base_dir):
            return count
        for f in os.listdir(base_dir):
            if not os.path.isfile(os.path.join(base_dir, f)):
                count += 1
        return count

    def _gen_run_string(self):
        run_index = self._count_subdirs(SUMMARY_BASE_DIR)
        lr = self.mainQN.LEARNING_RATE
        beta = self.mainQN.BETA_W
        out = '%.2g_%.2g_%d' % (lr, beta, run_index)
        return out

    def gen_target_ops(self):
        trainable_variables = tf.trainable_variables()
        total_vars = len(trainable_variables)
        print("Trainable Variables: %d" % total_vars)
        self.target_ops = []
        for idx, var in enumerate(trainable_variables[0:total_vars // 2]):
            # convex combination of new and old values
            new_val = (var.value() * TAU) + ((1 - TAU) * trainable_variables[idx + total_vars // 2].value())
            self.target_ops.append(trainable_variables[idx + total_vars // 2].assign(new_val))

    def update_target(self):
        """Set the target network to be equal to the primary network"""
        for op in self.target_ops:
            self.sess.run(op)

    def _load_model(self):
        try:
            print('Loading Model...')
            if os.path.exists(BASE_DIR):
                ckpt = tf.train.get_checkpoint_state(BASE_DIR)
                print('Loading %s' % ckpt.model_checkpoint_path)
                self.saver.restore(self.sess, ckpt.model_checkpoint_path)
                return
        except Exception:
            print("LOADING FAILED")
            if not os.path.exists(BASE_DIR):
                os.makedirs(BASE_DIR)
            self.sess.run(tf.global_variables_initializer())
            traceback.print_exc()

    def __enter__(self):
        self.start_time = time.time()
        self.walker = Walker(self.is_displaying)
        self.explore_prob = 0 if self.no_explore else START_EXPLOIT_PROB
        self.training_buffer = ExperienceBuffer()
        self.episodes_scores = []

        tf.reset_default_graph()
        self.mainQN = QNetwork(self.walker.get_state_sizes(), self.walker.action_size())
        # self.targetQN = QNetwork(self.walker.get_state_sizes(), self.walker.action_size())
        self.saver = tf.train.Saver()
        # self.gen_target_ops()
        self.sess = tf.Session()
        self.merged_summary = tf.summary.merge_all()
        self.file_writer = tf.summary.FileWriter(os.path.join(SUMMARY_BASE_DIR, self._gen_run_string()))
        self.file_writer.add_graph(self.sess.graph)
        self._load_model()
        return self

    def __exit__(self, type, value, tb):
        self.file_writer.close()
        self._save_tf_model()

    def __init__(self, is_displaying, no_explore, use_keyboard):
        self.is_displaying = is_displaying
        self.no_explore = no_explore
        self.total_steps = 0

    def _save_tf_model(self, index=0):
        try:
            self.saver.save(self.sess, '%s/model-%d.cptk' % (BASE_DIR, index))
            print("Saved model")
        except Exception:
            print("SAVING FAILED!")
            traceback.print_exc()

    def _episode_summery(self, index, pace_count):
        elapsed = time.time() - self.start_time
        print("Episode %d -\tScore %.2f\tSteps: %d\tTime: %.2f sec" %
        (index, self.episodes_scores[-1], pace_count * STEPS_IN_PACE, elapsed))
        self.start_time = time.time()
        if self.total_steps > PRE_TRAIN_STEPS:
            for i in range(POST_EPISODE_TRAINS):
                print("Replay training: %d / %d" % (i, POST_EPISODE_TRAINS), end='\r')
                self._batch_train_QN()
            self._batch_train_QN(True)

        if index % EPISODES_BETWEEN_SAVE == 0:
            self._save_tf_model(index)
        if index % EPISODES_BETWEEN_BIG_SUMMERY == 0:
            avg_score = np.mean(self.episodes_scores)
            self.episodes_scores = []
            print("Average scores: %.2f" % avg_score)
            print("Total Q: %.2f" % self.mainQN.pop_total_q())
            print("Explore probability: %.2f" % self.explore_prob)
            print("L2 of weights: %.2f" % self.sess.run(self.mainQN.regularizers))
            print("In replay memory: %d / %d" % (len(self.training_buffer.buffer), self.training_buffer.buffer_size))
            max_good_threshold = 10
            min_good_threshold = 0
            trimmed_score = max(min(avg_score, max_good_threshold), min_good_threshold)
            trimmed_score = trimmed_score / (max_good_threshold - min_good_threshold)
            self.explore_prob = 0 if self.no_explore else 0.1 + 0.8 * (1 - trimmed_score)

    # def offline_train(self):
    #     while True:
    #         print("~")
    #         self._batch_train_QN2()
    # def _batch_train_QN2():
    #     train_batch = self.training_buffer.sample(BATCH_SIZE) #Get a random batch of experiences.
    #     #Below we perform the Double-DQN update to the target Q-values
    #     s = np.vstack(train_batch[:,0])
    #     a = np.vstack(train_batch[:,1])
    #     r = train_batch[:, 2]
    #     s1 = np.vstack(train_batch[:, 3])
    #     a1 = self.mainQN.predict(s1, self.sess)

    #     # feed_dict = self.targetQN.states_to_feed_dict(s1, a1)
    #     feed_dict = self.mainQN.states_to_feed_dict(s1, a1)
    #     # doubleQ = self.sess.run(self.targetQN.Q_est, feed_dict=feed_dict)[:,0]
    #     doubleQ = self.sess.run(self.mainQN.Q_est, feed_dict=feed_dict)[:,0]
    #     targetQ = r + (DISCOUNT * doubleQ)
    #     #Update the network with our target values.
    #     feed_dict = self.mainQN.states_to_feed_dict(s, a)
    #     feed_dict[self.mainQN.targetQ] = targetQ

    #     self.sess.run(self.mainQN.update_model, feed_dict = feed_dict)
    #     if self.total_steps % (TRAINS_BETWEEN_TF_SUMMARY * STEPS_BETWEEN_DQN_TRAIN) == 0:
    #         s = self.sess.run(self.merged_summary, feed_dict = feed_dict)
    #         self.file_writer.add_summary(s, self.total_steps)
    #         print("Summary added")

    #     # self.update_target() #Set the target network to be equal to the primary network.

    def train(self):
        print("Start of training")

        # do stuff
        # self.update_target()
        for i in range(NUM_EPISODES):
            pace_count = self._run_episode()
            self._episode_summery(i, pace_count)

    # pace is a run of a few steps, without interrupting, either in explore mode or exploit mode
    def _run_pace(self, state, replay_buffer):
        is_exploring = np.random.rand(1)[0] < self.explore_prob or self.total_steps < PRE_TRAIN_STEPS
        explore_action = np.zeros([self.mainQN.action_size])
        explore_mask = np.zeros([self.mainQN.action_size])
        if is_exploring:
            explore_action = np.random.randint(-1, 2, (self.mainQN.action_size))
            explore_mask = np.random.randint(0, 2, (self.mainQN.action_size))

        for step_index in range(STEPS_IN_PACE):
            new_state = self._run_step(state, replay_buffer, explore_action, explore_mask)
            self._post_step_update()
            if self.walker.score() < STOP_EPISODE_SCORE_THRESHOLD or \
               np.linalg.norm(np.array(new_state) - np.array(state)) < STOP_EPISODE_STATE_THRESHOLD:
                print('Walker is stuck, quiting')
                return None
            state = new_state
        return state

    def _post_step_update(self):
        self.total_steps += 1
        if self.total_steps <= PRE_TRAIN_STEPS:
            return

        # if self.explore_prob > END_EXPLOIT_PROB:
        #     self.explore_prob -= self.step_drop

    def _run_step(self, state, replay_buffer, explore_action, explore_mask):
        action = self.mainQN.predict(np.reshape(state, [1, -1]), self.sess)[0]
        if self.total_steps % 100 == 99:
            print(action)
        action = explore_mask * explore_action + (-explore_mask + 1) * action
        next_state, reward = self.walker.step(action)
        # Save the experience to our episode buffer.
        replay_buffer.add(np.reshape(np.array([state, action, reward, next_state]), [1, 4]))
        return next_state

    def _batch_train_QN(self, write_summary=False):
        train_batch = self.training_buffer.sample(BATCH_SIZE)  # Get a random batch of experiences.
        # Below we perform the Double-DQN update to the target Q-values
        s = np.vstack(train_batch[:, 0])
        a = np.vstack(train_batch[:, 1])
        r = train_batch[:, 2]
        s1 = np.vstack(train_batch[:, 3])
        a1 = self.mainQN.predict(s1, self.sess)

        # feed_dict = self.targetQN.states_to_feed_dict(s1, a1)
        feed_dict = self.mainQN.states_to_feed_dict(s1, a1)
        # doubleQ = self.sess.run(self.targetQN.Q_est, feed_dict=feed_dict)[:,0]I
        doubleQ = self.sess.run(self.mainQN.Q_est, feed_dict=feed_dict)[:, 0]
        targetQ = r + (DISCOUNT * doubleQ)
        feed_dict = self.mainQN.states_to_feed_dict(s, a)
        feed_dict[self.mainQN.targetQ] = targetQ

        self.sess.run(self.mainQN.update_model, feed_dict=feed_dict)
        try:
            if write_summary:
                print("Adding summary...", end='\r')
                s = self.sess.run(self.merged_summary, feed_dict=feed_dict)
                self.file_writer.add_summary(s, self.total_steps)
                print("Summary added\t\t")
        except Exception:
            print("SUMMARY WRITING FAILED")
            # traceback.print_exc()
        # self.update_target() #Set the target network to be equal to the primary network.

    def _run_episode(self):
        episode_buffer = ExperienceBuffer()
        # Reset environment and get first new observation
        state = self.walker.reset()
        for pace_index in range(MAX_PACES_IN_EPISODE):
            state = self._run_pace(state, episode_buffer)
            if state is None:
                break

        self.training_buffer.add(episode_buffer.buffer)
        self.episodes_scores.append(self.walker.score())
        return pace_index + 1

    def show(self):
        state = self.walker.reset()

        from panda3d.core import KeyboardButton
        is_down = base.mouseWatcherNode.is_button_down
        ups = [KeyboardButton.ascii_key(char) for char in (b'q', b'w', b'e')]
        downs = [KeyboardButton.ascii_key(char) for char in (b'a', b's', b'd')]
        # import pdb; pdb.set_trace()
        while True:
            # action = self.mainQN.predict(np.vstack(state).transpose(), self.sess)[0]
            action = np.zeros(len(self.walker.joints))
            action[[is_down(button) for button in ups]] = 1.0
            action[[is_down(button) for button in downs]] = -1.0
            self.walker.step(action.tolist())
            if is_down(KeyboardButton.ascii_key(b'r')):
                self.walker.reset()


def main():
    is_displaying = False
    no_explore = False
    use_keyboard = False
    if len(sys.argv) > 1:
        is_displaying, no_explore, use_keyboard = \
        {"show": (True, False, False),
         "expl": (True, True, False),
         "kbrd": (True, False, True)}[sys.argv[1]]
    with Learner(is_displaying, no_explore, use_keyboard) as learner:
        if use_keyboard:
            learner.show()
            return
        learner.train()


if __name__ == "__main__":
    main()
