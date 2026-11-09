from collections import deque
from datetime import datetime
import logging
import os
import pprint as pp
import time

import numpy as np
import tensorflow as tf

from .tf_utils import shape


class TFBaseModel(object):

    """
    Base class providing common functionality for training TensorFlow models.

    This class handles the boilerplate code required to train TensorFlow models,
    including:

    - Computational graph initialization.
    - Optimizer configuration and gradient clipping.
    - Training and validation loops.
    - Loss and metric tracking.
    - Early stopping and learning rate restarts.
    - Model checkpointing and restoration.
    - Exponential moving average of model parameters.
    - Batch prediction and parameter export.

    Subclasses must implement `calculate_loss()`, which constructs and returns
    the loss tensor. They are also responsible for defining any placeholders,
    prediction tensors, metrics, and other model-specific graph components.

    The reader must provide generators that yield dictionaries mapping
    placeholder attribute names to NumPy batch arrays.

    Args:
        reader: Data reader providing train_batch_generator(),
            val_batch_generator(), and test_batch_generator().
        batch_sizes: Batch sizes used for successive training stages.
        num_training_steps: Maximum number of training steps.
        learning_rates: Learning rates corresponding to each training stage.
        beta1_decays: Beta1 decay values passed to the optimizer.
        optimizer: Optimizer type: 'adam', 'gd', or 'rms'.
        grad_clip: Maximum absolute value allowed for individual gradients.
        regularization_constant: Coefficient applied to L2 parameter
            regularization. Zero disables regularization.
        keep_prob: Dropout keep probability during training.
        patiences: Number of steps to wait for validation improvement
            before triggering early stopping or a restart.
        warm_start_init_step: Checkpoint step from which training resumes.
            Zero initializes the model from scratch.
        enable_parameter_averaging: Whether to maintain exponential moving
            averages of trainable parameters.
        min_steps_to_checkpoint: Minimum training step before saving a
            checkpoint during normal training.
        log_interval: Number of training steps between logging operations.
        logging_level: Logging verbosity level.
        loss_averaging_window: Number of recent batches used to calculate
            moving averages of losses, metrics, and execution times.
        validation_batch_size: Batch size used during validation.
        log_dir: Directory where training logs are stored.
        checkpoint_dir: Directory where model checkpoints are stored.
        prediction_dir: Directory where prediction outputs are stored.
    """

    def __init__(
        self,
        reader=None,
        batch_sizes=[128],
        num_training_steps=20000,
        learning_rates=[.01],
        beta1_decays=[.99],
        optimizer='adam',
        grad_clip=5,
        regularization_constant=0.0,
        keep_prob=1.0,
        patiences=[3000],
        warm_start_init_step=0,
        enable_parameter_averaging=False,
        min_steps_to_checkpoint=100,
        log_interval=20,
        logging_level=logging.INFO,
        loss_averaging_window=100,
        validation_batch_size=64,
        log_dir='logs',
        checkpoint_dir='checkpoints',
        prediction_dir='predictions',
    ):
        """
        Initialize model configuration, logging, and TensorFlow session.

        Training parameters are organized into stages. Each stage can use
        a different batch size, learning rate, beta1 decay, and patience.

        The number of stages is determined by the length of batch_sizes.

        Args:
            See TFBaseModel class documentation.
        """

        assert len(batch_sizes) == len(learning_rates) == len(patiences)
        self.batch_sizes = batch_sizes
        self.learning_rates = learning_rates
        self.beta1_decays = beta1_decays
        self.patiences = patiences
        self.num_restarts = len(batch_sizes) - 1
        self.restart_idx = 0
        self.update_train_params()

        self.reader = reader
        self.num_training_steps = num_training_steps
        self.optimizer = optimizer
        self.grad_clip = grad_clip
        self.regularization_constant = regularization_constant
        self.warm_start_init_step = warm_start_init_step
        self.keep_prob_scalar = keep_prob
        self.enable_parameter_averaging = enable_parameter_averaging
        self.min_steps_to_checkpoint = min_steps_to_checkpoint
        self.log_interval = log_interval
        self.loss_averaging_window = loss_averaging_window
        self.validation_batch_size = validation_batch_size

        self.log_dir = log_dir
        self.logging_level = logging_level
        self.prediction_dir = prediction_dir
        self.checkpoint_dir = checkpoint_dir
        if self.enable_parameter_averaging:
            self.checkpoint_dir_averaged = checkpoint_dir + '_avg'

        self.init_logging(self.log_dir)
        logging.info('\nnew run with parameters:\n{}'.format(pp.pformat(self.__dict__)))

        self.graph = self.build_graph()
        self.session = tf.Session(graph=self.graph)
        logging.info('built graph')

    def update_train_params(self):
        """
        Update training hyperparameters for the current training stage.

        The restart_idx determines which batch size, learning rate,
        beta1 decay, and early stopping patience are selected.

        This method is called during initialization and whenever training
        restarts after a validation plateau.

        Attributes updated:
            batch_size: Current minibatch size.
            learning_rate: Current learning rate.
            beta1_decay: Current optimizer beta1 decay.
            early_stopping_steps: Current early stopping patience.
        """
        self.batch_size = self.batch_sizes[self.restart_idx]
        self.learning_rate = self.learning_rates[self.restart_idx]
        self.beta1_decay = self.beta1_decays[self.restart_idx]
        self.early_stopping_steps = self.patiences[self.restart_idx]

    def calculate_loss(self):
        """
        Construct and return the model's loss tensor.

        Subclasses must override this method and define the computational
        operations required to calculate the training loss.

        Returns:
            TensorFlow tensor representing the batch loss.

        Raises:
            NotImplementedError: If the subclass does not implement this method.
        """

        raise NotImplementedError('subclass must implement this')

    def fit(self):
        """
        Train the model using minibatches from the reader.

        The training loop performs the following operations:

        1. Initialize model variables or restore a previous checkpoint.
        2. Evaluate validation loss and metrics.
        3. Execute one training step.
        4. Track moving averages of losses, metrics, and execution times.
        5. Log training progress at regular intervals.
        6. Save checkpoints whenever validation performance improves.
        7. Trigger early stopping or restart training when validation
           performance stops improving.

        During a restart, the best checkpoint is restored and the next
        training stage's hyperparameters are applied.

        Returns:
            None. Training results are logged and checkpoints are saved.

        Side Effects:
            Updates model parameters, creates checkpoint files, and writes
            training logs.
        """

        with self.session.as_default():

            # Restore an existing checkpoint or initialize model variables
            if self.warm_start_init_step:
                self.restore(self.warm_start_init_step)
                step = self.warm_start_init_step
            else:
                self.session.run(self.init)
                step = 0

            train_generator = self.reader.train_batch_generator(self.batch_size)
            val_generator = self.reader.val_batch_generator(self.validation_batch_size)

            # Maintain moving averages using a fixed-size sliding window.
            train_loss_history = deque(maxlen=self.loss_averaging_window)
            val_loss_history = deque(maxlen=self.loss_averaging_window)
            train_time_history = deque(maxlen=self.loss_averaging_window)
            val_time_history = deque(maxlen=self.loss_averaging_window)

            if not hasattr(self, 'metrics'):
                self.metrics = {}

            metric_histories = {
                metric_name: deque(maxlen=self.loss_averaging_window) 
                for metric_name in self.metrics
            }
            best_validation_loss, best_validation_tstep = float('inf'), 0


            while step < self.num_training_steps:


                # validation evaluation
                val_start = time.time()
                val_batch_df = next(val_generator)

                # Map batch dictionary keys to their corresponding placeholders
                val_feed_dict = {
                    getattr(self, placeholder_name, None): data
                    for placeholder_name, data in val_batch_df.items() 
                    if hasattr(self, placeholder_name)
                }

                val_feed_dict.update({
                    self.learning_rate_var: self.learning_rate, 
                    self.beta1_decay_var: self.beta1_decay
                })

                if hasattr(self, 'keep_prob'):
                    val_feed_dict.update({self.keep_prob: 1.0})
                if hasattr(self, 'is_training'):
                    val_feed_dict.update({self.is_training: False})

                # Evaluate validation loss and additional model metrics
                results = self.session.run(
                    fetches=[self.loss] + self.metrics.values(),
                    feed_dict=val_feed_dict
                )

                val_loss = results[0]
                val_metrics = results[1:] if len(results) > 1 else []
                val_metrics = dict(zip(self.metrics.keys(), val_metrics))

                val_loss_history.append(val_loss)
                val_time_history.append(time.time() - val_start)

                for key in val_metrics:
                    metric_histories[key].append(val_metrics[key])

                # Optionally inspect intermediate tensors for numerical issues.
                if hasattr(self, 'monitor_tensors'):
                    for name, tensor in self.monitor_tensors.items():
                        [np_val] = self.session.run([tensor], feed_dict=val_feed_dict)
                        print(name)
                        print('min', np_val.min())
                        print('max', np_val.max())
                        print('mean', np_val.mean())
                        print('std', np_val.std())
                        print('nans', np.isnan(np_val).sum())
                        print()
                    print()
                    print()


                # train step
                train_start = time.time()
                train_batch_df = next(train_generator)
                train_feed_dict = {
                    getattr(self, placeholder_name, None): data
                    for placeholder_name, data in train_batch_df.items() 
                    if hasattr(self, placeholder_name)
                }

                train_feed_dict.update({self.learning_rate_var: self.learning_rate, self.beta1_decay_var: self.beta1_decay})

                # Enable dropout and training-specific behavior during training
                if hasattr(self, 'keep_prob'):
                    train_feed_dict.update({self.keep_prob: self.keep_prob_scalar})
                if hasattr(self, 'is_training'):
                    train_feed_dict.update({self.is_training: True})

                # Execute the optimization operation
                train_loss, _ = self.session.run(
                    fetches=[self.loss, self.step],
                    feed_dict=train_feed_dict
                )
                train_loss_history.append(train_loss)
                train_time_history.append(time.time() - train_start)


                # Logging and early stopping
                if step % self.log_interval == 0:
                    avg_train_loss = sum(train_loss_history) / len(train_loss_history)
                    avg_val_loss = sum(val_loss_history) / len(val_loss_history)
                    avg_train_time = sum(train_time_history) / len(train_time_history)
                    avg_val_time = sum(val_time_history) / len(val_time_history)
                    metric_log = (
                        "[[step {:>8}]]     "
                        "[[train {:>4}s]]     loss: {:<12}     "
                        "[[val {:>4}s]]     loss: {:<12}     "
                    ).format(
                        step,
                        round(avg_train_time, 4),
                        round(avg_train_loss, 8),
                        round(avg_val_time, 4),
                        round(avg_val_loss, 8),
                    )
                    early_stopping_metric = avg_val_loss
                    for metric_name, metric_history in metric_histories.items():
                        metric_val = sum(metric_history) / len(metric_history)
                        metric_log += '{}: {:<4}     '.format(metric_name, round(metric_val, 4))
                        if metric_name == self.early_stopping_metric:
                            early_stopping_metric = metric_val

                    logging.info(metric_log)

                    # Save a checkpoint whenever validation performance improves
                    if early_stopping_metric < best_validation_loss:
                        best_validation_loss = early_stopping_metric
                        best_validation_tstep = step
                        if step > self.min_steps_to_checkpoint:
                            self.save(step)
                            if self.enable_parameter_averaging:
                                self.save(step, averaged=True)

                    # Check whether validation performance has plateaued
                    if step - best_validation_tstep > self.early_stopping_steps:

                        # Stop if all configured restart stages have been exhausted.
                        if self.num_restarts is None or self.restart_idx >= self.num_restarts:
                            logging.info(
                                'best validation loss of {} at training step {}'.format(
                                    best_validation_loss, 
                                    best_validation_tstep
                                )
                            )
                            logging.info('early stopping - ending training.')
                            return

                        # Restore the best model and move to the next training stage
                        if self.restart_idx < self.num_restarts:
                            self.restore(best_validation_tstep)
                            step = best_validation_tstep
                            self.restart_idx += 1
                            self.update_train_params()
                            train_generator = self.reader.train_batch_generator(self.batch_size)

                step += 1

            # Ensure that a checkpoint is saved when training ends early
            # before the minimum checkpoint step
            if step <= self.min_steps_to_checkpoint:
                best_validation_tstep = step
                self.save(step)

                if self.enable_parameter_averaging:
                    self.save(step, averaged=True)

            logging.info('num_training_steps reached - ending training')

    def predict(self, chunk_size=256):
        """
        Generate predictions for the test dataset and export model outputs.

        Test batches are processed sequentially to avoid loading the entire
        dataset into memory.

        If prediction_tensors exists, its tensors are evaluated for every
        test batch and concatenated before being saved.

        If parameter_tensors exists, those tensors are evaluated once and
        saved separately.

        Args:
            chunk_size: Number of samples processed in each test batch.

        Returns:
            None. Prediction arrays are saved as .npy files.

        Side Effects:
            Creates prediction_dir if it does not exist and writes NumPy files.
        """
        if not os.path.isdir(self.prediction_dir):
            os.makedirs(self.prediction_dir)

        if hasattr(self, 'prediction_tensors'):
            prediction_dict = {tensor_name: [] for tensor_name in self.prediction_tensors}

            test_generator = self.reader.test_batch_generator(chunk_size)
            for i, test_batch_df in enumerate(test_generator):
                if i % 10 == 0:
                    print(i*len(test_batch_df))

                test_feed_dict = {
                    getattr(self, placeholder_name, None): data
                    for placeholder_name, data in test_batch_df.items() if hasattr(self, placeholder_name)
                }

                # Disable dropout and training behavior during inference
                if hasattr(self, 'keep_prob'):
                    test_feed_dict.update({self.keep_prob: 1.0})
                if hasattr(self, 'is_training'):
                    test_feed_dict.update({self.is_training: False})

                tensor_names, tf_tensors = zip(*self.prediction_tensors.items())
                np_tensors = self.session.run(
                    fetches=tf_tensors,
                    feed_dict=test_feed_dict
                )
                for tensor_name, tensor in zip(tensor_names, np_tensors):
                    prediction_dict[tensor_name].append(tensor)

            # Concatenate batch predictions and save each output tensor
            for tensor_name, tensor in prediction_dict.items():
                np_tensor = np.concatenate(tensor, 0)
                save_file = os.path.join(self.prediction_dir, '{}.npy'.format(tensor_name))
                logging.info('saving {} with shape {} to {}'.format(tensor_name, np_tensor.shape, save_file))
                np.save(save_file, np_tensor)

        # Export model parameters separately when parameter_tensors is defined
        if hasattr(self, 'parameter_tensors'):
            for tensor_name, tensor in self.parameter_tensors.items():
                np_tensor = tensor.eval(self.session)

                save_file = os.path.join(self.prediction_dir, '{}.npy'.format(tensor_name))
                logging.info('saving {} with shape {} to {}'.format(tensor_name, np_tensor.shape, save_file))
                np.save(save_file, np_tensor)

    def save(self, step, averaged=False):
        """
        Save model parameters to a TensorFlow checkpoint.

        Args:
            step: Training step used as the checkpoint suffix.
            averaged: If True, save exponential moving average parameters
                using saver_averaged and checkpoint_dir_averaged.
                Otherwise, save the regular model parameters.

        Returns:
            None.

        Side Effects:
            Creates the checkpoint directory if necessary and writes
            TensorFlow checkpoint files.
        """

        saver = self.saver_averaged if averaged else self.saver
        checkpoint_dir = self.checkpoint_dir_averaged if averaged else self.checkpoint_dir
        if not os.path.isdir(checkpoint_dir):
            logging.info('creating checkpoint directory {}'.format(checkpoint_dir))
            os.mkdir(checkpoint_dir)

        model_path = os.path.join(checkpoint_dir, 'model')
        logging.info('saving model to {}'.format(model_path))
        saver.save(self.session, model_path, global_step=step)

    def restore(self, step=None, averaged=False):
        """
        Restore model parameters from a TensorFlow checkpoint.

        If step is provided, the corresponding checkpoint is restored.
        Otherwise, the latest checkpoint in the selected directory is used.

        Args:
            step: Specific training step to restore. If None or zero,
                the latest available checkpoint is restored.
            averaged: Whether to restore exponential moving average
                parameters instead of regular parameters.

        Returns:
            None.

        Side Effects:
            Restores TensorFlow variables in the current session.
        """

        saver = self.saver_averaged if averaged else self.saver
        checkpoint_dir = self.checkpoint_dir_averaged if averaged else self.checkpoint_dir
        if not step:
            model_path = tf.train.latest_checkpoint(checkpoint_dir)
            logging.info('restoring model parameters from {}'.format(model_path))
            saver.restore(self.session, model_path)
        else:
            model_path = os.path.join(
                checkpoint_dir, 'model{}-{}'.format('_avg' if averaged else '', step)
            )
            logging.info('restoring model from {}'.format(model_path))
            saver.restore(self.session, model_path)

    def init_logging(self, log_dir):
        """
        Configure logging for the current training run.

        Creates the log directory if it does not exist and configures
        Python's root logger to write messages to a timestamped file
        and the console.

        Args:
            log_dir: Directory where the log file will be stored.

        Returns:
            None.

        Side Effects:
            Creates a log file and adds a console logging handler.
        """

        if not os.path.isdir(log_dir):
            os.makedirs(log_dir)

        date_str = datetime.now().strftime('%Y-%m-%d_%H-%M')
        log_file = 'log_{}.txt'.format(date_str)

        try:                 # Python 2
            reload(logging)  # bad
        except NameError:    # Python 3
            import logging
        logging.basicConfig(
            filename=os.path.join(log_dir, log_file),
            level=self.logging_level,
            format='[[%(asctime)s]] %(message)s',
            datefmt='%m/%d/%Y %I:%M:%S %p'
        )
        logging.getLogger().addHandler(logging.StreamHandler())

    def update_parameters(self, loss):
        """
        Construct optimizer operations and apply parameter updates.

        This method optionally adds L2 regularization to the supplied loss,
        computes gradients, clips them elementwise, and creates the
        optimization operation.

        If parameter averaging is enabled, exponential moving averages
        are updated after each optimizer step.

        Args:
            loss: TensorFlow tensor representing the original batch loss.

        Returns:
            None. The resulting optimization operation is assigned to
            self.step.

        Side Effects:
            Adds optimizer operations, gradient operations, and parameter
            statistics to the TensorFlow computational graph.
        """

        # Add L2 regularization to discourage excessively large parameters
        if self.regularization_constant != 0:
            l2_norm = tf.reduce_sum([tf.sqrt(tf.reduce_sum(tf.square(param))) for param in tf.trainable_variables()])
            loss = loss + self.regularization_constant*l2_norm

        optimizer = self.get_optimizer(self.learning_rate_var, self.beta1_decay_var)

        # Compute gradients of the loss with respect to trainable variables
        grads = optimizer.compute_gradients(loss)

        # Clip gradients elementwise to prevent excessively large updates
        clipped = [
            (tf.clip_by_value(g, -self.grad_clip, self.grad_clip), v_) 
            for g, v_ in grads
        ]

        # Ensure operations such as batch normalization updates execute
        # before applying the gradients
        update_ops = tf.get_collection(tf.GraphKeys.UPDATE_OPS)
        with tf.control_dependencies(update_ops):
            step = optimizer.apply_gradients(clipped, global_step=self.global_step)

        # Maintain exponential moving averages after each optimizer update
        if self.enable_parameter_averaging:
            maintain_averages_op = self.ema.apply(tf.trainable_variables())
            with tf.control_dependencies([step]):
                self.step = tf.group(maintain_averages_op)
        else:
            self.step = step

        # Log all model variables and their shapes
        logging.info('all parameters:')
        logging.info(pp.pformat([(var.name, shape(var)) for var in tf.global_variables()]))

        logging.info('trainable parameters:')
        logging.info(pp.pformat([(var.name, shape(var)) for var in tf.trainable_variables()]))

        logging.info('trainable parameter count:')
        logging.info(str(np.sum(np.prod(shape(var)) for var in tf.trainable_variables())))

    def get_optimizer(self, learning_rate, beta1_decay):
        """
        Create and return the configured TensorFlow optimizer.

        Args:
            learning_rate: TensorFlow scalar controlling the update step size.
            beta1_decay: Decay parameter passed to Adam or RMSProp.

        Returns:
            A TensorFlow optimizer instance.

        Raises:
            AssertionError: If the configured optimizer is unsupported.
        """

        if self.optimizer == 'adam':
            return tf.train.AdamOptimizer(learning_rate, beta1=beta1_decay)
        elif self.optimizer == 'gd':
            return tf.train.GradientDescentOptimizer(learning_rate)
        elif self.optimizer == 'rms':
            return tf.train.RMSPropOptimizer(learning_rate, decay=beta1_decay, momentum=0.9)
        else:
            assert False, 'optimizer must be adam, gd, or rms'

    def build_graph(self):
        """
        Construct the TensorFlow computational graph.

        Creates the shared training variables, builds the model loss,
        constructs optimizer operations, and initializes checkpoint savers.

        The model-specific loss computation is delegated to calculate_loss(),
        which must be implemented by subclasses.

        Returns:
            tf.Graph: Fully constructed TensorFlow computational graph.

        Graph components created:
            ema: Exponential moving average manager.
            global_step: Non-trainable variable tracking optimization steps.
            learning_rate_var: Learning rate placeholder variable.
            beta1_decay_var: Optimizer decay parameter variable.
            loss: Model-specific loss tensor.
            step: Training operation.
            saver: Saver for regular model parameters.
            saver_averaged: Saver for averaged parameters, if enabled.
            init: Operation initializing all global variables.
        """

        with tf.Graph().as_default() as graph:
            # Exponential moving average configuration
            self.ema = tf.train.ExponentialMovingAverage(decay=0.99)

            # Shared training variables
            self.global_step = tf.Variable(0, trainable=False)
            self.learning_rate_var = tf.Variable(0.0, trainable=False)
            self.beta1_decay_var = tf.Variable(0.0, trainable=False)

            # Build model-specific loss and optimization operations
            self.loss = self.calculate_loss()
            self.update_parameters(self.loss)

            # Create checkpoint savers
            self.saver = tf.train.Saver(max_to_keep=1)
            if self.enable_parameter_averaging:
                self.saver_averaged = tf.train.Saver(self.ema.variables_to_restore(), max_to_keep=1)

            # Create an operation to initialize all graph variables
            self.init = tf.global_variables_initializer()

            return graph
