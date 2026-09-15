import os
import torch
import torch.nn as nn
import torch.optim as optim
import torchvision
from torchvision import transforms
import torchvision.models as models
import numpy as np

from nvflare.app_opt.pt.model_persistence_format_manager import PTModelPersistenceFormatManager
from nvflare.app_common.abstract.model import make_model_learnable

DEVICE = "cuda:0" if torch.cuda.is_available() else "cpu"

def count_params(model):
    """
    Counts the total number of parameters in a model.
    """
    return sum(p.numel() for p in model.parameters())

class SmallTestNet(nn.Module):
    """
    Small CNN for CIFAR-10 (62,006 parameters).
    """
    def __init__(self):
        super().__init__()
        self.conv1 = nn.Conv2d(3, 6, 5)
        self.pool = nn.MaxPool2d(2, 2)
        self.conv2 = nn.Conv2d(6, 16, 5)
        self.fc1 = nn.Linear(16 * 5 * 5, 120)
        self.fc2 = nn.Linear(120, 84)
        self.fc3 = nn.Linear(84, 10)

    def forward(self, x):
        x = self.pool(F.relu(self.conv1(x)))
        x = self.pool(F.relu(self.conv2(x)))
        x = torch.flatten(x, 1)  # flatten all dimensions except batch
        x = F.relu(self.fc1(x))
        x = F.relu(self.fc2(x))
        x = self.fc3(x)
        return x

class LargeTestNet(nn.Module):
    """
    Larger CNN for CIFAR-10 (2,122,186 parameters).
    """
    def __init__(self):
        super().__init__()
        self.conv1 = nn.Conv2d(3, 32, 3, padding=1)
        self.conv2 = nn.Conv2d(32, 64, 3, padding=1)
        self.pool = nn.MaxPool2d(2, 2)
        self.relu = nn.ReLU()
        self.dropout = nn.Dropout(0.25)
        
        dummy = torch.zeros(1, 3, 32, 32)
        dummy = self.pool(self.conv1(dummy))
        dummy = self.pool(self.conv2(dummy))
        self.fc1_input_size = dummy.view(-1).shape[0]
        
        self.fc1 = nn.Linear(self.fc1_input_size, 512)
        self.fc2 = nn.Linear(512, 10)

    def forward(self, x):        
        x = self.relu(self.conv1(x))
        x = self.pool(x)
        x = self.relu(self.conv2(x))
        x = self.pool(x)
        x = x.view(x.size(0), -1)
        x = self.dropout(x)
        x = self.relu(self.fc1(x))
        x = self.fc2(x)
        return x

class ResNet50(nn.Module):
    """
    ResNet50 adapted for CIFAR-10 (23M+ parameters).
    """
    def __init__(self, num_classes=10, pretrained=False):
        super().__init__()
        self.model = models.resnet50(pretrained=pretrained)
        # Replace the final fully connected layer for CIFAR-10 (10 classes)
        self.model.fc = nn.Linear(self.model.fc.in_features, num_classes)

    def forward(self, x):
        return self.model(x)


class MLManager:
    """
    Manages model, data, and training for CIFAR-10 experiments.
    """
    def __init__(
        self,
        epochs: int = 1,
        lr: float = 0.001,
        momentum: float = 0.9,
        batch_size: int = 64,
        num_workers: int = 1,
        dataset_path: str = "/tmp/nvflare/data/cifar10",
        model_path: str = "/tmp/nvflare/data/cifar10/cifar_net.pth",
        model_type: str = "SmallTestNet",  # Options: "SmallTestNet", "LargeTestNet", "ResNet50"
        device=DEVICE,
        exclude_agg_layers = [],    # Layer that should not be aggregated, e.g., [batch_norm]
        encrypt_layers = [],  # ["conv1.bias", conv2.bias", "fc1.weight"]   # TODO: Assert if layer names are invalid
        exclude_vars=None,
    ):
        '''Initializes the Executor for secure aggregation.

        Args:
        leader_client_name (str): Name of the client designated as leader for CC operations.
            epochs (int): Number of local training epochs.
            lr (float): Learning rate for local training.
            momentum (float): Momentum for SGD optimizer.
            batch_size (int): Batch size for training and validation.
            num_workers (int): Number of workers for data loaders.
            dataset_path (str): Path to the CIFAR-10 dataset.
            model_path (str): Path to save the trained model.
            model_type (str): Type of neural network model to use (e.g., "SmallTestNet", "ResNet50").
            device (str): Device to use for PyTorch operations (e.g., "cuda:0" or "cpu").
            exclude_agg_layers (list): Layer names to exclude from aggregation and encryption.
            encrypt_layers (list): Layer names to encrypt. If empty, all eligible layers are encrypted.
            exclude_vars (list): Variables to exclude during model loading.
        '''
        self.epochs = epochs
        self.lr = lr
        self.momentum = momentum
        self.batch_size = batch_size
        self.num_workers = num_workers
        self.dataset_path = dataset_path
        self.model_path = model_path
        self.model_type = model_type
        self.device = device
        self.exclude_agg_layers = exclude_agg_layers
        self.encrypt_layers = encrypt_layers
        self.exclude_vars=exclude_vars

        self.net = None
        self.persistence_manager = None
        self.trainset = None
        self.trainloader = None
        self.testset = None
        self.testloader = None
        self.criterion = None
        self.optimizer = None
        self._default_train_conf = None

        self.padding = None     # TODO: during encryption, send padding along with the model (or calculate it) so that we don't have to save locally.

    def initialize_net_CIFAR10(self, num_clients, client_name):
        """
        Sets up CIFAR-10 dataset, data loaders, model, optimizer, and loss.
        """
        transform = transforms.Compose([transforms.ToTensor(), transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))])

        full_trainset = torchvision.datasets.CIFAR10(
            root=self.dataset_path, train=True, download=True, transform=transform
        )

        # Non-IID Data Distribution: Uniform random sampling of dataset
        n = len(full_trainset)//num_clients  # Number of samples per client
        split_indices = torch.randperm(len(full_trainset))[:n]
        self.trainset = torch.utils.data.Subset(full_trainset, split_indices)

        self.trainloader = torch.utils.data.DataLoader(
            self.trainset, batch_size=self.batch_size, shuffle=True, num_workers=self.num_workers
        )

        self.testset = torchvision.datasets.CIFAR10(
            root=self.dataset_path, train=False, download=True, transform=transform
        )
        self.testloader = torch.utils.data.DataLoader(
            self.testset, batch_size=self.batch_size, shuffle=False, num_workers=self.num_workers
        )

        self.net = self.get_model(self.model_type).to(self.device)

        self.criterion = nn.CrossEntropyLoss()
        self.optimizer = optim.SGD(self.net.parameters(), lr=self.lr, momentum=self.momentum)

        self._default_train_conf = {"train": {"model": type(self.net).__name__}}
        self.persistence_manager = PTModelPersistenceFormatManager(
            data=self.net.state_dict(), default_train_conf=self._default_train_conf
        )

    def get_model(self, model_type, **kwargs):
        """
        Returns a model instance based on model_type.
        """
        if model_type == "SmallTestNet":
            return SmallTestNet()
        elif model_type == "LargeTestNet":
            return LargeTestNet()
        elif model_type == "ResNet50":
            return ResNet50(**kwargs)
        else:
            raise ValueError(f"Unknown model_type: {model_type}")

    def load_local_model(self, run_dir):    # run_dir = run_dir = fl_ctx.get_engine().get_workspace().get_run_dir(fl_ctx.get_prop(ReservedKey.RUN_NUM))
        """
        Loads the local model from disk.
        """
        models_dir = os.path.join(run_dir, "models")
        if not os.path.exists(models_dir):
            return None

        self.persistence_manager = PTModelPersistenceFormatManager(
            data=torch.load(self.model_path), default_train_conf=self._default_train_conf
        )
        ml = self.persistence_manager.to_model_learnable(exclude_vars=self.exclude_vars)
        return ml

    def save_local_model(self, run_dir):
        """
        Saves the current model state to disk.
        """
        models_dir = os.path.join(run_dir, "models")
        if not os.path.exists(models_dir):
            os.makedirs(models_dir)
        ml = make_model_learnable(self.net.state_dict(), {})
        self.persistence_manager.update(ml)
        torch.save(self.persistence_manager.to_persistence_dict(), self.model_path)

    def get_model_weights(self, client_name):
        """
        Returns the current model's state dict (excluding excluded layers).
        """
        # Get the new state dict and send as weights
        weights = {k: v.cpu().numpy() for k, v in self.net.state_dict().items() if k not in self.exclude_agg_layers}
        return weights

    def local_train(self, client_name):
        """
        Runs local training for the configured number of epochs.
        """
        # Pre-train accuracy
        local_recv_accuracy = self.evaluate(self.net.state_dict())
        x=True #print(f"({client_name}: Aggregated/initial model: Accuracy on the 10000 test images: {local_recv_accuracy}")

        self.net.to(self.device)

        for epoch in range(self.epochs):  # loop over the dataset multiple times
            running_loss = 0.0
            for i, data in enumerate(self.trainloader, 0):
                inputs, labels = data[0].to(self.device), data[1].to(self.device)
                # zero the parameter gradients
                self.optimizer.zero_grad()
                # forward + backward + optimize
                outputs = self.net(inputs)
                loss = self.criterion(outputs, labels)
                loss.backward()
                self.optimizer.step()

                # print statistics
                running_loss += loss.item()
                if i % 2000 == 1999:  # print every 2000 mini-batches
                    # self.log_info(fl_ctx, f"[{epoch + 1}, {i + 1:5d}] loss: {running_loss / 2000:.3f}")
                    running_loss = 0.0

        # Post-train accuracy
        local_trained_accuracy = self.evaluate(self.net.state_dict())
        x=True #print(f"({client_name}: Local trained model. Accuracy on the 10000 test images: {local_trained_accuracy}")

    def evaluate(self, input_weights):
        """
        Evaluates the given model weights on the test set.

        Args:
            input_weights: State dict to evaluate.

        Returns:
            Accuracy percentage.
        """
        net = self.get_model(self.model_type)
        net.load_state_dict(input_weights)
        net.to(DEVICE)

        correct = 0
        total = 0
        # since we're not training, we don't need to calculate the gradients for our outputs
        with torch.no_grad():
            for data in self.testloader:
                images, labels = data[0].to(DEVICE), data[1].to(DEVICE)
                # calculate outputs by running images through the network
                outputs = net(images)
                # the class with the highest energy is what we choose as prediction
                _, predicted = torch.max(outputs.data, 1)
                total += labels.size(0)
                correct += (predicted == labels).sum().item()

        return 100 * correct // total

    def filter_net(self, cc_batch_size):
        """
        Filters out excluded layers and prepares encrypted/unencrypted batches.

        Returns:
            (batched_list, unencrypted_dict)
        """
        # Exclude layers specified in exclude_agg_layers
        filtered_state_dict = {k: v for k, v in self.net.state_dict().items() if k not in self.exclude_agg_layers}
        if self.encrypt_layers:
            encrypted_dict = {k: v for k, v in filtered_state_dict.items() if k in self.encrypt_layers}
            unencrypted_dict = {k: v.cpu().numpy() for k, v in filtered_state_dict.items() if k not in self.encrypt_layers}
        else:
            encrypted_dict = filtered_state_dict
            unencrypted_dict = {}
        batched_list, self.padding = self.net_to_batches(encrypted_dict, cc_batch_size)
        
        return batched_list, unencrypted_dict

    def net_to_batches(self, weights_dict, batchsize):
        """
        Converts weights dict to a list of batches for encryption.

        Returns:
            (batched_list, pad_len)
        """
        # Flatten and concatenate all weights
        flat_weights_list = []
        for k, v in weights_dict.items():
            flat_weights_list.append(v.cpu().flatten())
        flat_weights = np.concatenate(flat_weights_list).astype(np.float32)  # shape: (total_params,)

        # Batch the concatenated vector
        total_length = flat_weights.shape[0]
        pad_len = 0
        if total_length % batchsize != 0:
            pad_len = batchsize - (total_length % batchsize)
            flat_weights = np.concatenate([flat_weights, np.zeros(pad_len, dtype=np.float32)])
        batched_list = flat_weights.reshape(-1, batchsize).tolist()
        return batched_list, pad_len

    def flat_array_to_state_dict(self, flat_array, unencrypted_weights):
        """
        Reconstructs state dict from a flat array and unencrypted weights.
        """
        # Remove padding if needed  # TODO: Don't really need to remove padding; except if we are checking for received model's dimension.
        if self.padding > 0:
            flat_array = flat_array[:-self.padding]

        new_state_dict = {}
        idx = 0
        for k, v in self.net.state_dict().items():
            if k in self.exclude_agg_layers:    # Fallback: use local value for excluded layers
                new_state_dict[k] = v.clone()
                continue
            if unencrypted_weights and k in unencrypted_weights:    # If we have unencrypted weights, use them to update the state dict.
                new_state_dict[k] = torch.as_tensor(v)
                continue
            numel = v.numel()
            # Extract the slice for this layer
            layer_flat = flat_array[idx:idx+numel]
            # Reshape to original shape and convert to tensor
            new_state_dict[k] = torch.tensor(layer_flat, dtype=v.dtype).reshape(v.shape)
            idx += numel

        self.net.load_state_dict(new_state_dict)

    def reconstruct_net(self, state_dict, full_state_dict, exclude_agg_layers=None):
        """
        Merges received state dict into the local state dict, skipping excluded layers.
        """
        for layer in full_state_dict:
            if layer not in exclude_agg_layers and layer in state_dict:
                full_state_dict[layer] = state_dict[layer]
        return full_state_dict