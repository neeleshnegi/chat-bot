import os
import io
import pickle
import time
import bz2
import numpy as np

class TextLoader():
    def __init__(self, data_dir, batch_size, seq_length):
        self.data_dir = data_dir
        self.batch_size = batch_size
        self.seq_length = seq_length
        self.tensor_sizes = []

        self.tensor_file_template = os.path.join(data_dir, "data{}.npz")
        vocab_file = os.path.join(data_dir, "vocab.pkl")
        sizes_file = os.path.join(data_dir, "sizes.pkl")

        self.input_files = self._get_input_file_list(data_dir)
        self.input_file_count = len(self.input_files)

        if self.input_file_count < 1:
            raise ValueError("Input files not found. File names must end in '.txt' or '.bz2'.")

        if self._preprocess_required(vocab_file, sizes_file, self.tensor_file_template, self.input_file_count):
            t0 = time.time()
            print("Preprocessing the following files:")
            for i, filename in enumerate(self.input_files): print("   {}.\t{}".format(i+1, filename))
            print("Saving vocab file")
            self._save_vocab(vocab_file)

            for i, filename in enumerate(self.input_files):
                t1 = time.time()
                print("Preprocessing file {}/{} ({})... ".format(i+1, len(self.input_files), filename),
                        end='', flush=True)
                self._preprocess(self.input_files[i], self.tensor_file_template.format(i))
                self.tensor_sizes.append(self.tensor.size)
                print("done ({:.1f} seconds)".format(time.time() - t1), flush=True)

            with open(sizes_file, 'wb') as f:
                pickle.dump(self.tensor_sizes, f)

            print("Processed input data: {:,d} characters loaded ({:.1f} seconds)".format(
                    self.tensor.size, time.time() - t0))
        else:
            print("Loading vocab file...")
            self._load_vocab(vocab_file)
            print("Loading sizes file...")
            with open(sizes_file, 'rb') as f:
                self.tensor_sizes = pickle.load(f)
        self.tensor_batch_counts = [n // (self.batch_size * self.seq_length) for n in self.tensor_sizes]
        self.total_batch_count = sum(self.tensor_batch_counts)
        print("Total batch count: {:,d}".format(self.total_batch_count))

        self.tensor_index = -1

    def _preprocess_required(self, vocab_file, sizes_file, tensor_file_template, input_file_count):
        if not os.path.exists(vocab_file):
            print("No vocab file found. Preprocessing...")
            return True
        if not os.path.exists(sizes_file):
            print("No sizes file found. Preprocessing...")
            return True
        for i in range(input_file_count):
            if not os.path.exists(tensor_file_template.format(i)):
                print("Couldn't find {}. Preprocessing...".format(tensor_file_template.format(i)))
                return True
        return False

    def _get_input_file_list(self, data_dir):
        suffixes = ['.txt', '.bz2']
        input_file_list = []
        if os.path.isdir(data_dir):
            for walk_root, walk_dir, walk_files in os.walk(data_dir):
                for file_name in walk_files:
                    if file_name.startswith("."): continue
                    file_path = os.path.join(walk_root, file_name)
                    if file_path.endswith(suffixes[0]) or file_path.endswith(suffixes[1]):
                        input_file_list.append(file_path)
        else: raise ValueError("Not a directory: {}".format(data_dir))
        return sorted(input_file_list)

    def _save_vocab(self, vocab_file):
        self.chars = [chr(i) for i in range(128)]
        self.vocab_size = len(self.chars)
        self.vocab = dict(zip(self.chars, range(len(self.chars))))
        with open(vocab_file, 'wb') as f:
            pickle.dump(self.chars, f)
        print("Saved vocab (vocab size: {:,d})".format(self.vocab_size))

    def _load_vocab(self, vocab_file):
     
        with open(vocab_file, 'rb') as f:
            self.chars = pickle.load(f)
        self.vocab_size = len(self.chars)
        self.vocab = dict(zip(self.chars, range(len(self.chars))))

    def _preprocess(self, input_file, tensor_file):
        if input_file.endswith(".bz2"): file_reference = bz2.open(input_file, mode='rt')
        elif input_file.endswith(".txt"): file_reference = io.open(input_file, mode='rt')
        data = file_reference.read()
        file_reference.close()
    
        self.tensor = np.array(list(map(self.vocab.get, data)))
        self.tensor = self.tensor[self.tensor != np.array(None)].astype(int) 
        np.savez_compressed(tensor_file, tensor_data=self.tensor)

    def _load_preprocessed(self, tensor_index):
        self.reset_batch_pointer()
        if tensor_index == self.tensor_index:
            return
        print("loading tensor data file {}".format(tensor_index))
        tensor_file = self.tensor_file_template.format(tensor_index)
        with np.load(tensor_file) as loaded:
            self.tensor = loaded['tensor_data']
        self.tensor_index = tensor_index
 
        self.num_batches = self.tensor.size // (self.batch_size * self.seq_length)
        if self.tensor_batch_counts[tensor_index] != self.num_batches:
            print("Error in batch size! Expected {:,d}; found {:,d}".format(self.tensor_batch_counts[tensor_index],
                    self.num_batches))
        
        self.tensor = self.tensor[:self.num_batches * self.batch_size * self.seq_length]
       
        xdata = self.tensor
        ydata = np.copy(self.tensor) 
        ydata[:-1] = xdata[1:] 
        ydata[-1] = xdata[0]
   
        self.x_batches = np.split(xdata.reshape(self.batch_size, -1), self.num_batches, 1)
        self.y_batches = np.split(ydata.reshape(self.batch_size, -1), self.num_batches, 1)

    def next_batch(self):
        if self.tensor_index < 0:
            self._load_preprocessed(0)
        if self.pointer >= self.num_batches:
            self._load_preprocessed((self.tensor_index + 1) % self.input_file_count)
        x, y = self.x_batches[self.pointer], self.y_batches[self.pointer]
        self.pointer += 1
        return x, y

    def reset_batch_pointer(self):
        self.pointer = 0

    def cue_batch_pointer_to_epoch_fraction(self, epoch_fraction):
        step_target = (epoch_fraction - int(epoch_fraction)) * self.total_batch_count
        self._cue_batch_pointer_to_step_count(step_target)

    def _cue_batch_pointer_to_step_count(self, step_target):
        for i, n in enumerate(self.tensor_batch_counts):
            if step_target < n:
                break
            step_target -= n
        self.pointer = n
        self.current_tensor_index = i
        self._load_preprocessed(i)
